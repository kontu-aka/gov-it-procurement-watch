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
from dashboard_ui import STATUS_STYLES, record_card, saved_statuses, status_badge

st.set_page_config(
    page_title="政府調達データ分析ツール", page_icon="◈", layout="wide",
    initial_sidebar_state="auto",
)
st.html(f"<style>{(ROOT / 'assets/dashboard.css').read_text(encoding='utf-8')}</style>")

st.sidebar.html('<div class="brand-mark"><span class="brand-icon">G / PA</span><span>政府調達データ<br>分析ツール</span></div>')
st.sidebar.subheader("表示するデータ")

demo_mode = st.sidebar.checkbox(
    "公開サンプルで表示（オフライン）", value="--demo" in sys.argv, key="demo_mode",
)
data_root = ROOT / "data" / "samples" if demo_mode else DATA_ROOT
loaded = load_latest_baseline(data_root)
st.sidebar.html('<p class="sidebar-note">保存済みデータを表示します。<br>画面操作による再取得は行いません。</p>')
st.sidebar.divider()
st.sidebar.caption("対象機関")
st.sidebar.write("デジタル庁")
st.sidebar.caption("一般競争入札情報")
st.title("政府調達データ分析ツール")
st.html('<div class="eyebrow">Government Procurement Analytics</div>')
st.write("デジタル庁の公開調達情報を整理・可視化。新規掲載や前回からの変更をひと目で確認できます。")
st.caption("デジタル庁の公開情報を利用した非公式ツールです。")
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
diff = diff_display_state(data_root)
statuses = saved_statuses(diff)
summary = diff["result"]["summary"] if diff["state"] == "READY" else None

st.caption(f"取得日時：{fetched_at_label(snapshot)}｜保存データの表示")
with st.sidebar.expander("データの出典・保存情報"):
    st.caption(f"表示中のsnapshot：{loaded['path'].name}")
    st.caption("本プロジェクトが取得・加工・集計したデータです。デジタル庁公式サービスではありません。")
st.sidebar.link_button("元の調達情報ページを開く ↗", links["procurement"])

st.subheader("調達情報のサマリー")
with st.container(key="overview_kpis"):
    metric_cols = st.columns(6)
    cards = [
        ("listed", "取得件数", "現在掲載件数", kpis["listed"]),
        ("new", "新規掲載", "NEW", summary["new"] if summary else None),
        ("updated", "内容更新", "UPDATED", summary["updated"] if summary else None),
        ("not_listed", "今回の一覧から非掲載", "一覧から非掲載", summary["not_listed"] if summary else None),
        ("unchanged", "変更なし", "UNCHANGED", summary["unchanged"] if summary else None),
        ("quality", "データ品質警告", "データ品質WARN", kpis["validation_warn_items"]),
    ]
    for col, (key, caption, label, value) in zip(metric_cols, cards):
        with col.container(border=True, key=f"kpi_{key}"):
            st.caption(caption)
            if value is None:
                st.write("—")
                st.caption("比較結果なし")
            else:
                st.metric(label, value)
st.caption("取得件数・品質警告・集計は検索前の保存データ全件、差分は対応する保存済み比較結果の値です。")
if summary:
    st.caption(f"比較済み｜前回 {summary['total_previous']}件 → 今回 {summary['total_current']}件。非掲載は今回の取得件数に含みません。")
else:
    st.info(diff["message"])
st.caption("今回の一覧から非掲載は、案件の取消・終了・落札を意味しません。")

st.divider()
st.subheader("案件一覧")
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
st.html('<div class="status-legend">' + ''.join(status_badge(status) for status in ("NEW", "UPDATED", "NOT_LISTED", "UNCHANGED")) + '</div>')
st.caption("一覧の判定ラベルは保存済み比較結果に基づきます。今回の一覧にない案件は「前回との比較」に表示します。")
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
    card_tab, table_tab = st.tabs(["カードで見る", "表で見る"])
    with card_tab:
        st.html('<div class="record-list">' + ''.join(
            record_card(row, statuses.get(row["stable_key"]), safe_detail_url(row["detail_url"]))
            for row in filtered
        ) + '</div>')
    with table_tab:
        for table_row, row in zip(table_rows, filtered):
            status = statuses.get(row["stable_key"])
            table_row["前回比較"] = STATUS_STYLES.get(status, ("判定なし", "neutral"))[0]
        st.dataframe(
            table_rows, hide_index=True, width="stretch", row_height=64,
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

st.divider()
st.subheader("前回との比較")
if diff["state"] != "READY":
    st.caption("対応する比較結果が保存されると、ここに詳細を表示します。")
else:
    summary = diff["result"]["summary"]
    st.caption(f"差分結果：{diff['path'].name}")
    st.caption(f"比較済み｜前回 {summary['total_previous']}件／今回 {summary['total_current']}件"
               f"｜UNCHANGED {summary['unchanged']}件")
    if all(event["status"] == "UNCHANGED" for event in diff["result"]["events"]):
        st.info("NO CHANGE：比較済み・差分0件")
    changed_events = [event for event in diff["result"]["events"] if event["status"] != "UNCHANGED"]
    changes_tab, unchanged_tab = st.tabs([f"変化・確認が必要な案件（{len(changed_events)}）", f"変更なし（{summary['unchanged']}）"])
    for status, (label, _) in STATUS_STYLES.items():
        events = [event for event in diff["result"]["events"] if event["status"] == status]
        if not events:
            continue
        with (unchanged_tab if status == "UNCHANGED" else changes_tab):
            with st.container(key=f"diff_{status}"):
                st.html(status_badge(status))
                for event in events:
                    case = event["current"] or event["previous"]
                    title = case[0]["title"] if case else "案件情報なし"
                    with st.expander(f"{event['status']}｜{title}"):
                        for row in case:
                            st.html(record_card(row, event["status"], safe_detail_url(row["detail_url"])))
                        if event["changed_fields"]:
                            st.caption("保存された変更前・変更後の値")
                            st.json(event["changed_fields"], expanded=False)
                        else:
                            st.write(event["reason"] or label)
    st.caption("一覧から非掲載は、案件の取消・終了・落札を意味しません。")

st.divider()
st.subheader("保存データの集計")
with st.expander("案件名のキーワード集計", expanded=True):
    st.caption("デジタル庁公式カテゴリではなく、案件タイトルに対する単純キーワード集計です。AI分類やLLMは使用していません。")
    counts = keyword_counts(records)
    st.dataframe(
        [{"キーワード": keyword, "該当案件数": count} for keyword, count in counts.items()],
        hide_index=True, width="stretch",
    )
    st.caption("各キーワードは1案件につき最大1件として数えます。複数語に該当する案件があるため、列の合計は案件総数と一致しません。")
with st.expander("現在取得できている一覧データ内の月別件数"):
    st.caption("現在掲載分のsnapshotを集計した値です。デジタル庁の全調達案件の月別件数ではありません。")
    months = monthly_counts(records)
    st.dataframe(
        [{"掲載月": month, "案件数": count} for month, count in months.items()],
        hide_index=True, width="stretch",
    )

st.subheader("データ品質")
coverage_cols = st.columns(2)
coverage_cols[0].metric("案件番号あり", kpis["with_number"])
coverage_cols[1].metric("更新日記載あり", kpis["with_updated_date"])
quality_cols = st.columns(4)
quality_cols[0].metric("案件番号欠損", quality["procurement_number_missing"])
quality_cols[1].metric("詳細URL欠損", quality["detail_url_missing"])
quality_cols[2].metric("更新日未掲載", quality["updated_date_unpublished"])
quality_cols[3].metric("identity衝突候補", quality["identity_collision_groups"])
st.caption("更新日未掲載はサイト上で起こり得るため、品質エラーに含めません。identity衝突候補は同じ照合キーを持つグループ数です。")
st.caption("データ品質WARNは、保存済みvalidation.warningsの警告項目数です。更新日未掲載は含めません。")
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
