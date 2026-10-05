"""Read-only Streamlit view over validated local procurement snapshots."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from dashboard_data import (
    DATA_ROOT, diff_display_state, fetched_at_label, filter_records, keyword_counts,
    load_latest_baseline, monthly_counts, quality_summary, safe_detail_url,
    snapshot_kpis, source_links,
)

st.set_page_config(page_title="Gov IT Procurement Watch", layout="wide")

demo_mode = st.sidebar.checkbox(
    "公開サンプルで表示（オフライン）", value="--demo" in sys.argv, key="demo_mode",
)
data_root = ROOT / "data" / "samples" if demo_mode else DATA_ROOT
loaded = load_latest_baseline(data_root)
st.title("Gov IT Procurement Watch")
st.write("デジタル庁が公開する調達情報を低頻度で取得し、保存・差分検出・集計するポートフォリオ用デモ。")
if demo_mode:
    st.info("公開サンプル：2026年10月3日・4日の保存データを表示しています。現在の調達状況ではありません。")

if loaded["snapshot"] is None:
    st.error(loaded["reason"])
    for reason in loaded["rejected"][:5]:
        st.caption(reason)
    st.stop()

snapshot = loaded["snapshot"]
records = snapshot["records"]
links = source_links(snapshot)
kpis = snapshot_kpis(snapshot)
quality = quality_summary(snapshot)

st.caption("対象：一般競争入札情報｜データ出典：デジタル庁「調達情報」")
st.caption(f"取得日時：{fetched_at_label(snapshot)}｜表示中のsnapshot：{loaded['path'].name}")
st.caption("本プロジェクトが取得・加工・集計したデータです。デジタル庁公式サービスではありません。")
st.link_button("元の調達情報ページを開く", links["procurement"])

st.subheader("現在の一覧")
st.caption("以下のKPI・キーワード件数・月別件数は、検索前の正常snapshot全件を対象にしています。")
metric_cols = st.columns(4)
metric_cols[0].metric("現在掲載件数", kpis["listed"])
metric_cols[1].metric("案件番号あり", kpis["with_number"])
metric_cols[2].metric("更新日記載あり", kpis["with_updated_date"])
metric_cols[3].metric("データ品質WARN", kpis["validation_warn_items"])
st.caption("データ品質WARNは、保存済みvalidation.warningsの警告項目数です。更新日未掲載は含めません。")

st.subheader("案件を探す")
st.caption("検索・フィルターは下の案件一覧にだけ適用します。")
search_col, date_col, type_col = st.columns([2, 2, 1])
with search_col:
    title_query = st.text_input("案件名のキーワード", placeholder="例：クラウド")
available_dates = [date.fromisoformat(row["posted_date"]) for row in records]
with date_col:
    date_range = st.date_input(
        "掲載日の範囲",
        value=(min(available_dates), max(available_dates)),
        min_value=min(available_dates), max_value=max(available_dates),
    )
notice_types = sorted({row["notice_type"] for row in records if row.get("notice_type")})
with type_col:
    if len(notice_types) > 1:
        selected_type = st.selectbox("公告種別", ["すべて", *notice_types])
        notice_filter = None if selected_type == "すべて" else selected_type
    elif notice_types:
        st.caption("公告種別")
        st.write(notice_types[0])
        notice_filter = None
    else:
        st.caption("公告種別：未掲載")
        notice_filter = None
if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    posted_from, posted_to = date_range
else:
    posted_from = posted_to = None
    st.info("日付範囲の開始日と終了日を選ぶと、日付フィルターを適用します。")
filtered = filter_records(
    records, keyword=title_query, posted_from=posted_from,
    posted_to=posted_to, notice_type=notice_filter,
)
st.write(f"案件一覧：{len(filtered)}件／snapshot全体：{len(records)}件")
if not filtered:
    st.info("条件に該当する案件はありません。")
else:
    table_rows = [{
        "掲載日": row["posted_date"],
        "案件名": row["title"],
        "案件番号": row["procurement_number"] or "—",
        "公告種別": row["notice_type"] or "—",
        "更新日": row["updated_date"] or "—",
        "詳細リンク": safe_detail_url(row["detail_url"]),
    } for row in filtered]
    st.dataframe(
        table_rows, hide_index=True, width="stretch",
        column_config={
            "案件名": st.column_config.TextColumn("案件名", width="large"),
            "案件番号": st.column_config.TextColumn("案件番号"),
            "詳細リンク": st.column_config.LinkColumn("詳細リンク", display_text="詳細を開く"),
        },
    )
    with st.expander("案件名の全文と詳細リンクを確認する"):
        for index, row in enumerate(filtered, start=1):
            st.text(row["title"])
            st.caption(
                f"掲載日 {row['posted_date']}｜番号 {row['procurement_number'] or '未掲載'}"
                f"｜公告種別 {row['notice_type'] or '未掲載'}"
                f"｜更新日 {row['updated_date'] or '未掲載'}"
            )
            url = safe_detail_url(row["detail_url"])
            if url:
                st.link_button(f"詳細ページを開く（{index}）", url)
            else:
                st.caption("詳細リンクなし")
            st.divider()

st.subheader("案件名のキーワード集計")
st.caption("デジタル庁公式カテゴリではなく、案件タイトルに対する単純キーワード集計です。AI分類やLLMは使用していません。")
counts = keyword_counts(records)
st.dataframe(
    [{"キーワード": keyword, "該当案件数": count} for keyword, count in counts.items()],
    hide_index=True, width="stretch",
)
st.caption("各キーワードは1案件につき最大1件として数えます。複数語に該当する案件があるため、列の合計は案件総数と一致しません。")

st.subheader("現在取得できている一覧データ内の月別件数")
st.caption("現在掲載分のsnapshotを集計した値です。デジタル庁の全調達案件の月別件数ではありません。")
months = monthly_counts(records)
st.dataframe(
    [{"掲載月": month, "案件数": count} for month, count in months.items()],
    hide_index=True, width="stretch",
)

st.subheader("前回との比較")
diff = diff_display_state(data_root)
if diff["state"] != "READY":
    st.info(diff["message"])
else:
    summary = diff["result"]["summary"]
    st.caption(f"差分結果：{diff['path'].name}")
    cols = st.columns(3)
    cols[0].metric("NEW", summary["new"])
    cols[1].metric("UPDATED", summary["updated"])
    cols[2].metric("一覧から非掲載", summary["not_listed"])
    st.caption(f"比較済み｜前回 {summary['total_previous']}件／今回 {summary['total_current']}件"
               f"｜UNCHANGED {summary['unchanged']}件")
    if all(event["status"] == "UNCHANGED" for event in diff["result"]["events"]):
        st.info("NO CHANGE：比較済み・差分0件")
    for event in diff["result"]["events"]:
        if event["status"] == "UNCHANGED":
            continue
        case = (event["current"] or event["previous"])
        title = case[0]["title"] if case else "案件情報なし"
        with st.expander(f"{event['status']}｜{title}"):
            if event["changed_fields"]:
                st.json(event["changed_fields"], expanded=False)
            else:
                st.write(event["reason"] or event["status"])
    st.caption("一覧から非掲載は、案件の取消・終了・落札を意味しません。")

st.subheader("データ品質")
quality_cols = st.columns(4)
quality_cols[0].metric("案件番号欠損", quality["procurement_number_missing"])
quality_cols[1].metric("詳細URL欠損", quality["detail_url_missing"])
quality_cols[2].metric("更新日未掲載", quality["updated_date_unpublished"])
quality_cols[3].metric("identity衝突候補", quality["identity_collision_groups"])
st.caption("更新日未掲載はサイト上で起こり得るため、品質エラーに含めません。identity衝突候補は同じ照合キーを持つグループ数です。")
st.write(f"validation status：{quality['validation_result']}")
for warning in quality["validation_warnings"]:
    st.warning(str(warning))
if loaded["rejected"]:
    st.caption(f"本番snapshot候補のうち、検証で除外したファイル：{len(loaded['rejected'])}件")

st.subheader("出典と利用条件")
st.markdown(
    f"出典：[デジタル庁「調達情報」]({links['procurement']})。"
    "本プロジェクトが公開一覧情報を取得・加工・集計しています。"
    "デジタル庁公式サービスではありません。"
)
st.markdown(
    f"[デジタル庁コピーライトポリシー]({links['copyright']})に従い、"
    f"[公共データ利用規約 PDL1.0]({links['pdl']})の対象公開情報を利用しています。"
    "外部調達ポータルの本文は取得していません。"
)
