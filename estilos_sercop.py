"""
estilos_sercop.py — Capa visual premium para SERCOP Analytics (Streamlit)

Uso (al inicio de app.py, después de st.set_page_config):

    from estilos_sercop import aplicar_estilos
    aplicar_estilos()

Opcional — color semántico en las tarjetas KPI: añade una clase modificadora
al generar cada tarjeta, por ejemplo:

    <div class="sercop-kpi-card kpi--ok">       → Adjudicada / Finalizada
    <div class="sercop-kpi-card kpi--info">     → Ejecución de Contrato
    <div class="sercop-kpi-card kpi--danger">   → Desierta / Cancelado
    <div class="sercop-kpi-card kpi--warn">     → Suspendido
    <div class="sercop-kpi-card kpi--total">    → Total
"""

import streamlit as st

CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

:root{
  --ink-950:#0b1220; --ink-900:#111827; --ink-700:#334155; --ink-500:#64748b; --ink-400:#94a3b8;
  --paper:#f6f7f9; --card:#ffffff; --line:rgba(15,23,42,.07); --line-strong:rgba(15,23,42,.12);
  --accent:#1d4ed8; --accent-soft:rgba(29,78,216,.08);
  --ok:#047857; --ok-soft:#ecfdf5; --info:#1d4ed8; --info-soft:#eff6ff;
  --warn:#b45309; --warn-soft:#fffbeb; --danger:#be123c; --danger-soft:#fff1f2;
  --r-lg:18px; --r-md:12px;
  --shadow: 0 1px 2px rgba(15,23,42,.04), 0 8px 24px -12px rgba(15,23,42,.10);
  --shadow-hover: 0 2px 4px rgba(15,23,42,.05), 0 18px 40px -16px rgba(15,23,42,.18);
  --ease: cubic-bezier(.2,.7,.2,1);
}

/* ───────── Base ───────── */
html, body, [data-testid="stApp"], [data-testid="stApp"] *:not(.material-icons):not([translate="no"]):not(.notranslate){
  font-family:'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
[data-testid="stApp"]{ background:var(--paper); }
[data-testid="stHeader"]{ background:transparent; }
[data-testid="stDecoration"]{ display:none; }
[data-testid="stMainBlockContainer"]{ padding-top:2.25rem !important; padding-bottom:4rem; max-width:1320px; }

/* Jerarquía tipográfica */
/* st.title / st.header → título de página; st.subheader → título de sección */
[data-testid="stMain"] h1, [data-testid="stMain"] h2{ font-weight:900 !important; letter-spacing:-.035em; color:var(--ink-950); font-size:2.25rem !important; line-height:1.15 !important; }
[data-testid="stMain"] h3{ font-weight:700 !important; letter-spacing:-.02em; color:var(--ink-900); font-size:1.15rem !important; margin-top:.5rem; }
[data-testid="stMain"] h4{ font-weight:600 !important; color:var(--ink-700); font-size:.95rem !important; }
[data-testid="stCaptionContainer"]{ color:var(--ink-500); }
[data-testid="stMain"] hr{ border-color:var(--line) !important; margin:1.75rem 0 !important; }

/* ───────── Sidebar ───────── */
[data-testid="stSidebar"]{ background:linear-gradient(180deg,#0f172a 0%,#111a2e 100%); border-right:1px solid rgba(255,255,255,.04); }
[data-testid="stSidebar"] .sercop-nav-label{ letter-spacing:.14em; font-size:.68rem !important; color:var(--ink-400) !important; }
[data-testid="stSidebar"] [data-testid="stButton"] button,
[data-testid="stSidebar"] [data-testid="stLinkButton"] a{
  border-radius:var(--r-md) !important; border:1px solid transparent !important;
  font-weight:500 !important; font-size:.86rem !important; letter-spacing:.03em; justify-content:flex-start !important;
  transition:background .25s var(--ease), border-color .25s var(--ease), transform .25s var(--ease);
}
[data-testid="stSidebar"] [data-testid="stButton"] button > div,
[data-testid="stSidebar"] [data-testid="stLinkButton"] a > div{ justify-content:flex-start !important; text-align:left !important; width:100%; }
[data-testid="stSidebar"] [data-testid="stButton"] button p,
[data-testid="stSidebar"] [data-testid="stLinkButton"] a p{ white-space:normal !important; text-overflow:clip !important; overflow:visible !important; text-align:left; }
[data-testid="stSidebar"] [data-testid="stButton"] button:hover,
[data-testid="stSidebar"] [data-testid="stLinkButton"] a:hover{
  background:rgba(255,255,255,.06) !important; border-color:rgba(255,255,255,.06) !important; transform:translateX(2px);
}
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"]{
  background:rgba(96,165,250,.14) !important; box-shadow:inset 3px 0 0 #60a5fa; color:#fff !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] details{
  border-radius:var(--r-md) !important; border-color:rgba(255,255,255,.08) !important; background:rgba(255,255,255,.02);
}

/* ───────── Tarjetas KPI (contador) ───────── */
.sercop-kpi-card{
  background:var(--card) !important; border:1px solid var(--line) !important; border-radius:var(--r-lg) !important;
  box-shadow:var(--shadow) !important; padding:1.25rem 1.35rem !important; position:relative; overflow:hidden;
  transition:transform .3s var(--ease), box-shadow .3s var(--ease), border-color .3s var(--ease);
}
.sercop-kpi-card:hover{ transform:translateY(-2px) scale(1.01); box-shadow:var(--shadow-hover) !important; border-color:var(--line-strong) !important; }
.sercop-kpi-card::before{ content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--kpi-c, var(--ink-400)); opacity:.9; }
.sercop-kpi-card > div:nth-child(1){
  font-size:.82rem !important; font-weight:600 !important; color:var(--ink-500) !important; letter-spacing:.01em;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:flex; align-items:center; gap:.35rem;
}
.sercop-kpi-card > div:nth-child(1) .notranslate{ color:var(--kpi-c, var(--ink-400)); font-size:1rem !important; }
.sercop-kpi-card > div:nth-child(2){
  font-size:2.35rem !important; font-weight:800 !important; letter-spacing:-.04em; color:var(--ink-950) !important;
  font-variant-numeric:tabular-nums; line-height:1.1 !important; margin:.6rem 0 .35rem !important;
}
.sercop-kpi-card > div:nth-child(3) span{
  display:inline-flex; align-items:center; padding:.2rem .55rem !important; border-radius:999px !important;
  font-size:.72rem !important; font-weight:700 !important; font-variant-numeric:tabular-nums;
  background:var(--kpi-soft, #f1f5f9) !important; color:var(--kpi-c, var(--ink-700)) !important;
}
.kpi--total { --kpi-c:var(--ink-900); --kpi-soft:#f1f5f9; }
.kpi--ok    { --kpi-c:var(--ok);     --kpi-soft:var(--ok-soft); }
.kpi--info  { --kpi-c:var(--info);   --kpi-soft:var(--info-soft); }
.kpi--warn  { --kpi-c:var(--warn);   --kpi-soft:var(--warn-soft); }
.kpi--danger{ --kpi-c:var(--danger); --kpi-soft:var(--danger-soft); }

/* ───────── Contenedores con borde (tarjetas de presupuesto, etc.) ───────── */
[data-testid="stMain"] [data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"]{
  border-radius:var(--r-lg) !important;
}
[data-testid="stMain"] [data-testid="stColumn"] [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] [data-testid="stPlotlyChart"]):has(> [data-testid="stElementContainer"] [data-testid="stMarkdown"]){
  background:var(--card) !important; border:1px solid var(--line); border-radius:var(--r-lg); box-shadow:var(--shadow);
  transition:transform .3s var(--ease), box-shadow .3s var(--ease);
}
[data-testid="stMain"] [data-testid="stColumn"] [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] [data-testid="stPlotlyChart"]):has(> [data-testid="stElementContainer"] [data-testid="stMarkdown"]):hover{
  transform:translateY(-2px); box-shadow:var(--shadow-hover);
}
/* valores monetarios grandes: que no se desborden */
[data-testid="stMain"] [data-testid="stColumn"] [data-testid="stMarkdownContainer"] > div:not(.sercop-kpi-card) > div:first-child + div{
  font-variant-numeric:tabular-nums; letter-spacing:-.03em; font-weight:800 !important;
  font-size:clamp(1.3rem, 1.9vw, 1.9rem) !important; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
[data-testid="stMain"] [data-testid="stColumn"] [data-testid="stMarkdownContainer"] > div:not(.sercop-kpi-card) > div:first-child{
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}

/* ───────── Filtros ───────── */
[data-testid="stWidgetLabel"] p{ font-size:.74rem !important; font-weight:600 !important; color:var(--ink-500) !important; text-transform:uppercase; letter-spacing:.06em; }
/* Streamlit 1.67 dejo BaseWeb (data-baseweb) por React Aria: el contenedor visible del select es
   `.react-aria-ComboBox > [role="group"]` y el del date_input `[data-testid="stDateInputField"]`.
   Se mantienen los selectores BaseWeb para versiones anteriores. */
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div,
[data-testid="stSelectbox"] .react-aria-ComboBox > [role="group"],
[data-testid="stMultiSelect"] .react-aria-ComboBox > [role="group"],
[data-testid="stMain"] [data-testid="stDateInput"] [data-testid="stDateInputField"]{
  background:var(--card) !important; border:1px solid var(--line-strong) !important; border-radius:var(--r-md) !important;
  box-shadow:0 1px 2px rgba(15,23,42,.03);
  transition:border-color .25s var(--ease), box-shadow .25s var(--ease);
}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:hover,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div:hover,
[data-testid="stSelectbox"] .react-aria-ComboBox > [role="group"]:hover,
[data-testid="stMultiSelect"] .react-aria-ComboBox > [role="group"]:hover,
[data-testid="stMain"] [data-testid="stDateInput"] [data-testid="stDateInputField"]:hover{ border-color:rgba(15,23,42,.22) !important; }
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div:focus-within,
[data-testid="stSelectbox"] .react-aria-ComboBox > [role="group"]:focus-within,
[data-testid="stMultiSelect"] .react-aria-ComboBox > [role="group"]:focus-within,
[data-testid="stMain"] [data-testid="stDateInput"] [data-testid="stDateInputField"]:focus-within{
  border-color:var(--accent) !important; box-shadow:0 0 0 4px var(--accent-soft) !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"],
[data-testid="stMultiSelect"] [data-tag]{ background:var(--accent-soft) !important; color:var(--accent) !important; border-radius:8px !important; }

/* ───────── Botones del área principal ───────── */
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]{
  background:var(--card) !important; border:1px solid var(--line-strong) !important; border-radius:var(--r-md) !important;
  color:var(--ink-700) !important; font-weight:600 !important; font-size:.85rem !important;
  box-shadow:0 1px 2px rgba(15,23,42,.04); transition:all .25s var(--ease);
}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:hover{ border-color:var(--ink-400) !important; color:var(--ink-950) !important; transform:translateY(-1px); box-shadow:var(--shadow); }
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:active{ transform:translateY(0) scale(.98); }
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:focus-visible{ box-shadow:0 0 0 4px var(--accent-soft) !important; border-color:var(--accent) !important; }

/* ───────── Expander ───────── */
[data-testid="stMain"] [data-testid="stExpander"] details{
  background:var(--card); border:1px solid var(--line) !important; border-radius:var(--r-md) !important; box-shadow:var(--shadow);
}
[data-testid="stMain"] [data-testid="stExpander"] summary{ font-weight:600; color:var(--ink-700); transition:color .2s; }
[data-testid="stMain"] [data-testid="stExpander"] summary:hover{ color:var(--accent); }

/* ───────── Pestañas (segmented control) ───────── */
[data-testid="stTabs"] [role="tablist"]{
  gap:.25rem; background:#eef0f3; padding:.3rem; border-radius:14px; width:fit-content; max-width:100%; overflow-x:auto;
  border:none !important;
}
[data-testid="stTabs"] [role="tablist"] > div[data-baseweb="tab-highlight"],
[data-testid="stTabs"] [role="tablist"] > div[data-baseweb="tab-border"],
[data-testid="stTabs"] .react-aria-SelectionIndicator{ display:none !important; }
[data-testid="stTab"]{
  border-radius:10px !important; padding:.45rem .9rem !important; height:auto !important; color:var(--ink-500) !important;
  font-weight:600 !important; white-space:nowrap; transition:all .25s var(--ease);
}
[data-testid="stTab"]:hover{ color:var(--ink-900) !important; background:rgba(255,255,255,.6); }
[data-testid="stTab"][aria-selected="true"]{ background:var(--card) !important; color:var(--ink-950) !important; box-shadow:0 1px 3px rgba(15,23,42,.10); }
[data-testid="stTab"] p{ font-size:.82rem !important; }

/* ───────── Tablas (st.table) ───────── */
[data-testid="stTable"]{ background:var(--card); border:1px solid var(--line); border-radius:var(--r-lg); box-shadow:var(--shadow); overflow-x:auto; }
[data-testid="stTable"] table{ border:none !important; width:100%; border-collapse:collapse; }
[data-testid="stTable"] thead th{
  background:#f8fafc !important; color:var(--ink-500) !important; font-size:.7rem !important; font-weight:700 !important;
  text-transform:uppercase; letter-spacing:.05em; border:none !important; border-bottom:1px solid var(--line-strong) !important;
  padding:.75rem .85rem !important; text-align:right !important; vertical-align:bottom;
}
/* columna índice vacía de pandas: oculta (o usa hide_index en el código) */
[data-testid="stTable"] table:has(tbody th) thead th:first-child, [data-testid="stTable"] tbody th{ display:none; }
[data-testid="stTable"] table:has(tbody th) thead th:nth-child(2),
[data-testid="stTable"] table:not(:has(tbody th)) thead th:first-child{ text-align:left !important; }
[data-testid="stTable"] tbody td{
  border:none !important; border-bottom:1px solid var(--line) !important; padding:.65rem .85rem !important;
  font-size:.85rem; color:var(--ink-700);
}
[data-testid="stTable"] tbody td:first-of-type{ color:var(--ink-900); font-weight:500; }
[data-testid="stTable"] tbody td:not(:first-of-type){ text-align:right; font-variant-numeric:tabular-nums; }
[data-testid="stTable"] tbody td:last-of-type{ white-space:nowrap; font-weight:600; color:var(--ink-900); }
[data-testid="stTable"] tbody tr{ transition:background .2s var(--ease); }
[data-testid="stTable"] tbody tr:hover{ background:#f8fafc; }
[data-testid="stTable"] tbody tr:last-child td{ border-bottom:none !important; }

/* ───────── Alertas y gráficos ───────── */
[data-testid="stAlert"] > div{ border-radius:var(--r-md) !important; border:1px solid var(--line) !important; }
[data-testid="stPlotlyChart"]{ border-radius:var(--r-md); }
</style>
"""


def aplicar_estilos() -> None:
    """Inyecta la hoja de estilos global. Llamar una sola vez por página."""
    st.markdown(CSS, unsafe_allow_html=True)
