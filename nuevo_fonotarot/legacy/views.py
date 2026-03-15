"""LegacyPHP blueprint views — Python port of the old PHP admin reports.

Each route corresponds to one PHP file in php-legacy/.
The original PHP ran one query per day (up to 93 per page); this port
consolidates those into single GROUP BY queries for performance.

HTML output intentionally preserves the original dark-theme styling.
No site template is applied — each view is a standalone page.
"""

import calendar

from flask import render_template

from . import legacy_bp
from .db import audiotex_conn, firenze_conn, portal_conn
from ..decorators import login_required_modal
from ..log import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal query helpers
# ---------------------------------------------------------------------------


def _fetch_monthly_3carrier(year: int, month: int, entel_field: str = "fonotarot-cl") -> dict:
    """Return per-day minute totals for 3 carriers from the CDR table.

    Replaces 93 individual daily SELECT queries with 3 GROUP BY queries.

    Returns:
        dict with keys ``days`` (list of daily row dicts) and
        ``totals`` (dict with keys entel/alotarot/latam/total).
    """
    _, days_in_month = calendar.monthrange(year, month)
    start = f"{year}-{month:02d}-01"
    next_month = month % 12 + 1
    next_year = year + (1 if month == 12 else 0)
    end = f"{next_year}-{next_month:02d}-01"

    carriers = {
        "entel": entel_field,
        "alotarot": "alotarot",
        "latam": "latam",
    }
    by_day: dict[int, dict] = {}

    with portal_conn() as conn:
        with conn.cursor() as cur:
            for key, userfield in carriers.items():
                cur.execute(
                    """
                    SELECT DAY(calldate) AS dia,
                           FLOOR(SUM(billsec) / 60) AS minutos
                    FROM cdr
                    WHERE disposition = 'ANSWERED'
                      AND zvn_clientid > 1
                      AND userfield = %s
                      AND calldate >= %s
                      AND calldate < %s
                    GROUP BY DAY(calldate)
                    """,
                    (userfield, start, end),
                )
                for row in cur.fetchall():
                    d = int(row["dia"])
                    by_day.setdefault(d, {"entel": 0, "alotarot": 0, "latam": 0})
                    by_day[d][key] = int(row["minutos"] or 0)

    days = []
    totals = {"entel": 0, "alotarot": 0, "latam": 0, "total": 0}
    for d in range(1, days_in_month + 1):
        row = by_day.get(d, {"entel": 0, "alotarot": 0, "latam": 0})
        row_total = row["entel"] + row["alotarot"] + row["latam"]
        days.append(
            {
                "date": f"{d:02d}-{month:02d}-{year}",
                "entel": row["entel"],
                "alotarot": row["alotarot"],
                "latam": row["latam"],
                "total": row_total,
            }
        )
        totals["entel"] += row["entel"]
        totals["alotarot"] += row["alotarot"]
        totals["latam"] += row["latam"]
        totals["total"] += row_total

    return {"days": days, "totals": totals}


def _fetch_agent_monthly_cdr(
    year: int,
    month: int,
    dst_numbers: tuple,
    duration_col: str = "billsec",
    min_duration: int = 90,
) -> dict:
    """Return per-day minute totals for a single agent from the CDR table.

    Replaces 31 individual daily SELECT queries with one GROUP BY query.
    duration_col is 'billsec' for most agents, 'duration' for paulina01.
    """
    _, days_in_month = calendar.monthrange(year, month)
    start = f"{year}-{month:02d}-01"
    next_month = month % 12 + 1
    next_year = year + (1 if month == 12 else 0)
    end = f"{next_year}-{next_month:02d}-01"

    placeholders = ", ".join(["%s"] * len(dst_numbers))

    with portal_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DAY(calldate) AS dia,
                       FLOOR(SUM({duration_col}) / 60) AS minutos
                FROM cdr
                WHERE disposition = 'ANSWERED'
                  AND zvn_clientid > 1
                  AND dst IN ({placeholders})
                  AND {duration_col} > %s
                  AND calldate >= %s
                  AND calldate < %s
                GROUP BY DAY(calldate)
                """,
                (*dst_numbers, min_duration, start, end),
            )
            by_day = {int(r["dia"]): int(r["minutos"] or 0) for r in cur.fetchall()}

    days = []
    total = 0
    for d in range(1, days_in_month + 1):
        mins = by_day.get(d, 0)
        days.append({"date": f"{d:02d}-{month:02d}-{year}", "minutos": mins})
        total += mins

    return {"days": days, "total": total}


# ---------------------------------------------------------------------------
# Agent registry — single source of truth for 7XXX extensions
# ---------------------------------------------------------------------------
# Keys are the agent's internal extension number (7XXX).
# Marilina (7000): her PHP filename had no numeric suffix; 7000 is a placeholder.
# Paulina's feb-2024 report used duration/min_duration=0 (see paulina01 below);
# the registry keeps the current billsec/90 convention for forward-looking queries.
AGENT_REGISTRY: dict[int, dict] = {
    7000: {"name": "Marilina", "dst": (56332541220, 56990238293, 56999679182), "duration_col": "billsec", "min_duration": 90},
    7001: {"name": "Paulina",  "dst": (56976341921, 56232326345),              "duration_col": "billsec", "min_duration": 90},
    7005: {"name": "Maite",    "dst": (56997130343,),                          "duration_col": "billsec", "min_duration": 90},
    7006: {"name": "Paola",    "dst": (56652893541, 56994871981, 56952379063), "duration_col": "billsec", "min_duration": 90},
    7007: {"name": "Angela",   "dst": (56232500587, 56984597737),              "duration_col": "billsec", "min_duration": 90},
    7008: {"name": "Altair",   "dst": (56994662528, 56227239476),              "duration_col": "billsec", "min_duration": 90},
    7009: {"name": "Karla",    "dst": (56947739514, 56225064742),              "duration_col": "billsec", "min_duration": 90},
    7012: {"name": "Pedro",    "dst": (56233134177, 56959516081, 56999047069), "duration_col": "billsec", "min_duration": 90},
    7014: {"name": "Alex",     "dst": (56991023392, 56352411071),              "duration_col": "billsec", "min_duration": 90},
    7015: {"name": "Violeta",  "dst": (56967654876, 56352410599),              "duration_col": "billsec", "min_duration": 90},
}


def _fetch_all_agents_monthly_cdr(
    year: int,
    month: int,
    agent_ids: tuple | None = None,
) -> dict:
    """Return per-day minute totals for all (or selected) agents from the CDR table.

    Args:
        year: Report year.
        month: Report month (1–12).
        agent_ids: Optional tuple of 7XXX extension numbers to include.
                   If None, all agents in AGENT_REGISTRY are included.

    Returns:
        dict with keys:
          ``agents``  — list of {ext, name} sorted by extension.
          ``days``    — list of per-day dicts {date, <ext>: mins, …, total: int}.
          ``totals``  — dict {<ext>: total_mins, …}.
    """
    _, days_in_month = calendar.monthrange(year, month)
    start = f"{year}-{month:02d}-01"
    next_month = month % 12 + 1
    next_year = year + (1 if month == 12 else 0)
    end = f"{next_year}-{next_month:02d}-01"

    selected = {
        ext: info
        for ext, info in AGENT_REGISTRY.items()
        if agent_ids is None or ext in agent_ids
    }

    by_day: dict[int, dict] = {}

    with portal_conn() as conn:
        with conn.cursor() as cur:
            for ext, info in selected.items():
                dst_numbers = info["dst"]
                duration_col = info["duration_col"]
                min_duration = info["min_duration"]
                placeholders = ", ".join(["%s"] * len(dst_numbers))
                cur.execute(
                    f"""
                    SELECT DAY(calldate) AS dia,
                           FLOOR(SUM({duration_col}) / 60) AS minutos
                    FROM cdr
                    WHERE disposition = 'ANSWERED'
                      AND zvn_clientid > 1
                      AND dst IN ({placeholders})
                      AND {duration_col} > %s
                      AND calldate >= %s
                      AND calldate < %s
                    GROUP BY DAY(calldate)
                    """,
                    (*dst_numbers, min_duration, start, end),
                )
                for row in cur.fetchall():
                    d = int(row["dia"])
                    by_day.setdefault(d, {e: 0 for e in selected})
                    by_day[d][ext] = int(row["minutos"] or 0)

    agents = [{"ext": ext, "name": info["name"]} for ext, info in sorted(selected.items())]
    totals: dict[int, int] = {ext: 0 for ext in selected}
    days = []
    for d in range(1, days_in_month + 1):
        row_base = by_day.get(d, {ext: 0 for ext in selected})
        row: dict = {"date": f"{d:02d}-{month:02d}-{year}"}
        row_total = 0
        for ext in selected:
            mins = row_base.get(ext, 0)
            row[ext] = mins
            totals[ext] += mins
            row_total += mins
        row["total"] = row_total
        days.append(row)

    return {"agents": agents, "days": days, "totals": totals}


def _fetch_prepago_ddi(year: int, month: int, ddi_numbers: tuple) -> dict:
    """Return per-day minute totals from callsprepago filtered by ddi.

    Used by alotarot.php (prepago lines).
    """
    _, days_in_month = calendar.monthrange(year, month)
    start = f"{year}-{month:02d}-01"
    next_month = month % 12 + 1
    next_year = year + (1 if month == 12 else 0)
    end = f"{next_year}-{next_month:02d}-01"

    placeholders = ", ".join(["%s"] * len(ddi_numbers))

    with portal_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DAY(time) AS dia,
                       FLOOR(SUM(billsec) / 60) AS minutos
                FROM callsprepago
                WHERE SUBSTRING(time, 1, 10) >= %s
                  AND SUBSTRING(time, 1, 10) < %s
                  AND duration > 60
                  AND ddi IN ({placeholders})
                GROUP BY DAY(time)
                """,
                (start, end, *ddi_numbers),
            )
            by_day = {int(r["dia"]): int(r["minutos"] or 0) for r in cur.fetchall()}

    days = []
    total = 0
    for d in range(1, days_in_month + 1):
        mins = by_day.get(d, 0)
        days.append({"date": f"{d:02d}-{month:02d}-{year}", "minutos": mins})
        total += mins

    return {"days": days, "total": total}


def _fetch_prepago_ssi(year: int, month: int, ssi_numbers: tuple) -> dict:
    """Return per-day minute totals from callsprepago filtered by ssi.

    Used by pedromaritza.php.
    """
    _, days_in_month = calendar.monthrange(year, month)
    start = f"{year}-{month:02d}-01"
    next_month = month % 12 + 1
    next_year = year + (1 if month == 12 else 0)
    end = f"{next_year}-{next_month:02d}-01"

    placeholders = ", ".join(["%s"] * len(ssi_numbers))

    with portal_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DAY(time) AS dia,
                       FLOOR(SUM(duration) / 60) AS minutos
                FROM callsprepago
                WHERE SUBSTRING(time, 1, 10) >= %s
                  AND SUBSTRING(time, 1, 10) < %s
                  AND duration > 60
                  AND ssi IN ({placeholders})
                GROUP BY DAY(time)
                """,
                (start, end, *ssi_numbers),
            )
            by_day = {int(r["dia"]): int(r["minutos"] or 0) for r in cur.fetchall()}

    days = []
    total = 0
    for d in range(1, days_in_month + 1):
        mins = by_day.get(d, 0)
        days.append({"date": f"{d:02d}-{month:02d}-{year}", "minutos": mins})
        total += mins

    return {"days": days, "total": total}


def _db_error(exc: Exception) -> str:
    """Render a plain error page when the legacy DB is unreachable."""
    logger.error("Legacy DB unavailable: %s", exc, exc_info=True)
    return (
        f"<html><body style='background:#000418;color:#f74129;font-family:monospace;"
        f"padding:2rem'><h2>Legacy DB unavailable</h2><pre>{exc}</pre></body></html>"
    ), 503


# ---------------------------------------------------------------------------
# Operator status panels  (zvn_audiotex_legacy → operators table)
# ---------------------------------------------------------------------------


@legacy_bp.route("/ejecutivosfonotarot.php")
@login_required_modal
def ejecutivosfonotarot():
    """Operator panel for Fonotarot — auto-refreshes every 10 s."""
    logger.debug("legacy: ejecutivosfonotarot requested")
    try:
        with audiotex_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM operators
                    WHERE type IN (7) AND loggedin = '1'
                    ORDER BY available DESC, loggedin DESC
                    """
                )
                operators = cur.fetchall()
    except Exception as exc:
        return _db_error(exc)

    return render_template(
        "legacy/operators_panel.html",
        title="Ejecutivos Fonotarot",
        operators=operators,
        refresh_url="/legacy/ejecutivosfonotarot.php",
        refresh_secs=10,
        link_base="https://www.fonotarot.com",
        show_link=True,
    )


@legacy_bp.route("/ejecutivosalotarottest.php")
@login_required_modal
def ejecutivosalotarottest():
    """Operator panel for Alotarot (test) — alternates with testx on refresh."""
    logger.debug("legacy: ejecutivosalotarottest requested")
    try:
        with audiotex_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM operators
                    WHERE type IN (7) AND loggedin = '1'
                    ORDER BY available DESC, loggedin DESC
                    """
                )
                operators = cur.fetchall()
    except Exception as exc:
        return _db_error(exc)

    return render_template(
        "legacy/operators_panel.html",
        title="Ejecutivos Alotarot",
        operators=operators,
        refresh_url="/legacy/ejecutivosalotarottestx.php",
        refresh_secs=10,
        link_base=None,
        show_link=False,
    )


@legacy_bp.route("/ejecutivosalotarottestx.php")
@login_required_modal
def ejecutivosalotarottestx():
    """Operator panel for Alotarot (testx) — alternates with test on refresh."""
    logger.debug("legacy: ejecutivosalotarottestx requested")
    try:
        with audiotex_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM operators
                    WHERE type IN (7) AND loggedin = '1'
                    ORDER BY available DESC, loggedin DESC
                    """
                )
                operators = cur.fetchall()
    except Exception as exc:
        return _db_error(exc)

    return render_template(
        "legacy/operators_panel.html",
        title="Ejecutivos Alotarot",
        operators=operators,
        refresh_url="/legacy/ejecutivosalotarottest.php",
        refresh_secs=10,
        link_base=None,
        show_link=False,
    )


# ---------------------------------------------------------------------------
# Live calls panel  (zvn_firenze → onlinecalls)
# ---------------------------------------------------------------------------


@legacy_bp.route("/indexfirenzex.php")
@login_required_modal
def indexfirenzex():
    """Live calls in progress — auto-refreshes every 5 s."""
    logger.debug("legacy: indexfirenzex requested")
    try:
        with firenze_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT TIMEDIFF(NOW(), modified_at) AS resultado,
                           operator,
                           client_id
                    FROM onlinecalls
                    """
                )
                calls = cur.fetchall()
    except Exception as exc:
        return _db_error(exc)

    return render_template(
        "legacy/live_calls.html",
        calls=calls,
        refresh_url="/legacy/indexfirenzex.php",
        refresh_secs=5,
    )


# ---------------------------------------------------------------------------
# Recent CDR views  (zvn_asterisk → cdr)
# ---------------------------------------------------------------------------


@legacy_bp.route("/ultimas.php")
@login_required_modal
def ultimas():
    """Last 100 CDR records — calldate, dst, duration — auto-refreshes 15 s."""
    logger.debug("legacy: ultimas requested")
    try:
        with portal_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT calldate, dst, duration, disposition, zvn_clientid
                    FROM cdr
                    ORDER BY calldate DESC
                    LIMIT 100
                    """
                )
                rows = cur.fetchall()
    except Exception as exc:
        return _db_error(exc)

    return render_template(
        "legacy/recent_calls.html",
        rows=rows,
        refresh_url="/legacy/ultimas.php",
        refresh_secs=15,
    )


@legacy_bp.route("/laatste.php")
@login_required_modal
def laatste():
    """Last 100 CDR records with extra columns — auto-refreshes 15 s."""
    logger.debug("legacy: laatste requested")
    try:
        with portal_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT calldate, dst, duration, disposition,
                           zvn_clientid, dcontext, lastdata
                    FROM cdr
                    ORDER BY calldate DESC
                    LIMIT 100
                    """
                )
                rows = cur.fetchall()
    except Exception as exc:
        return _db_error(exc)

    return render_template(
        "legacy/recent_calls_extended.html",
        rows=rows,
        refresh_url="/legacy/laatste.php",
        refresh_secs=15,
    )


# ---------------------------------------------------------------------------
# Monthly 3-carrier CDR reports  (fonotarot-cl / alotarot / latam)
# ---------------------------------------------------------------------------


@legacy_bp.route("/ene26.php")
@login_required_modal
def ene26():
    """January 2026 — fonotarot-cl, alotarot, latam."""
    logger.debug("legacy: ene26 requested")
    try:
        data = _fetch_monthly_3carrier(2026, 1)
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="ENE 2026", **data)


@legacy_bp.route("/feb26.php")
@login_required_modal
def feb26():
    """February 2026 — fonotarot-cl, alotarot, latam."""
    logger.debug("legacy: feb26 requested")
    try:
        data = _fetch_monthly_3carrier(2026, 2)
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="FEB 2026", **data)


@legacy_bp.route("/maart26.php")
@login_required_modal
def maart26():
    """March 2026 — fonotarot-cl, alotarot, latam."""
    logger.debug("legacy: maart26 requested")
    try:
        data = _fetch_monthly_3carrier(2026, 3)
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="MAR 2026", **data)


@legacy_bp.route("/oct25.php")
@login_required_modal
def oct25():
    """October 2025 — fonotarot-cl, alotarot, latam."""
    logger.debug("legacy: oct25 requested")
    try:
        data = _fetch_monthly_3carrier(2025, 10)
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="OCT 2025", **data)


@legacy_bp.route("/nov25.php")
@login_required_modal
def nov25():
    """November 2025 — fonotarot-clx variant, alotarot, latam."""
    logger.debug("legacy: nov25 requested")
    try:
        data = _fetch_monthly_3carrier(2025, 11, entel_field="fonotarot-clx")
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="NOV 2025", **data)


@legacy_bp.route("/DIC25.php")
@login_required_modal
def dic25():
    """December 2025 — fonotarot-cl, alotarot, latam."""
    logger.debug("legacy: dic25 requested")
    try:
        data = _fetch_monthly_3carrier(2025, 12)
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="DIC 2025", **data)


@legacy_bp.route("/sept25.php")
@login_required_modal
def sept25():
    """September 2025 — fonotarot-cl, alotarot, latam."""
    logger.debug("legacy: sept25 requested")
    try:
        data = _fetch_monthly_3carrier(2025, 9)
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="SEPT 2025", **data)


@legacy_bp.route("/sept24.php")
@login_required_modal
def sept24():
    """September 2024 — fonotarot-cl, alotarot, latam."""
    logger.debug("legacy: sept24 requested")
    try:
        data = _fetch_monthly_3carrier(2024, 9)
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="SEPT 2024", **data)


@legacy_bp.route("/alotarotoct.php")
@login_required_modal
def alotarotoct():
    """November 2025 alternate view — fonotarot-clx, alotarot, latam."""
    logger.debug("legacy: alotarotoct requested")
    try:
        data = _fetch_monthly_3carrier(2025, 11, entel_field="fonotarot-clx")
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/monthly_3carriers.html", title="NOV 2025", **data)


# ---------------------------------------------------------------------------
# Individual agent monthly reports  (zvn_asterisk → cdr, filtered by dst)
# ---------------------------------------------------------------------------
# DEPRECATED — these hardcoded per-agent, per-month routes are superseded by
# the consolidated Flask-Admin view (Reportes → Reporte Agentes).
# Kept for backward compatibility with bookmarked URLs; do not add new ones.


@legacy_bp.route("/alex14.php")
@login_required_modal
def alex14():
    """Alex — March 2026, dst 56991023392 / 56352411071."""
    logger.debug("legacy: alex14 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56991023392, 56352411071)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Alex", **data)


@legacy_bp.route("/angela7.php")
@login_required_modal
def angela7():
    """Angela — March 2026, dst 56232500587 / 56984597737."""
    logger.debug("legacy: angela7 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56232500587, 56984597737)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Angela", **data)


@legacy_bp.route("/karla9.php")
@login_required_modal
def karla9():
    """Karla — March 2026, dst 56947739514 / 56225064742."""
    logger.debug("legacy: karla9 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56947739514, 56225064742)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Karla", **data)


@legacy_bp.route("/karla99.php")
@login_required_modal
def karla99():
    """Karla — October 2025, dst 56947739514 / 56225064742."""
    logger.debug("legacy: karla99 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2025, 10, (56947739514, 56225064742)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Karla (oct)", **data)


@legacy_bp.route("/maite5.php")
@login_required_modal
def maite5():
    """Maite — March 2026, dst 56997130343."""
    logger.debug("legacy: maite5 requested")
    try:
        data = _fetch_agent_monthly_cdr(2026, 3, (56997130343,))
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Maite", **data)


@legacy_bp.route("/marilina.php")
@login_required_modal
def marilina():
    """Marilina — March 2026, dst 56332541220 / 56990238293 / 56999679182."""
    logger.debug("legacy: marilina requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56332541220, 56990238293, 56999679182)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Marilina", **data)


@legacy_bp.route("/paola6.php")
@login_required_modal
def paola6():
    """Paola — March 2026, dst 56652893541 / 56994871981 / 56952379063."""
    logger.debug("legacy: paola6 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56652893541, 56994871981, 56952379063)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Paola", **data)


@legacy_bp.route("/paulina01.php")
@login_required_modal
def paulina01():
    """Paulina — February 2024.

    Uses ``duration`` column instead of ``billsec``; no min_duration filter.
    Original PHP also used duration, not billsec.
    """
    logger.debug("legacy: paulina01 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2024, 2, (56976341921, 56232326345),
            duration_col="duration",
            min_duration=0,
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Paulina (feb24)", **data)


@legacy_bp.route("/paulina1.php")
@login_required_modal
def paulina1():
    """Paulina — March 2026, dst 56976341921 / 56232326345."""
    logger.debug("legacy: paulina1 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56976341921, 56232326345)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Paulina", **data)


@legacy_bp.route("/pedro12.php")
@login_required_modal
def pedro12():
    """Pedro — March 2026, dst 56233134177 / 56959516081 / 56999047069.

    The original PHP had a typo ``03-2026`` as one of the dst values
    (which MySQL would evaluate as the integer -2023).  That value is
    omitted here; only the three valid phone numbers are kept.
    """
    logger.debug("legacy: pedro12 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56233134177, 56959516081, 56999047069)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Pedro", **data)


@legacy_bp.route("/violeta15.php")
@login_required_modal
def violeta15():
    """Violeta — March 2026, dst 56967654876 / 56352410599."""
    logger.debug("legacy: violeta15 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56967654876, 56352410599)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Violeta", **data)


@legacy_bp.route("/altair8.php")
@login_required_modal
def altair8():
    """Altair — March 2026, dst 56994662528 / 56227239476."""
    logger.debug("legacy: altair8 requested")
    try:
        data = _fetch_agent_monthly_cdr(
            2026, 3, (56994662528, 56227239476)
        )
    except Exception as exc:
        return _db_error(exc)
    return render_template("legacy/agent_monthly.html", title="Altair", **data)


# ---------------------------------------------------------------------------
# Prepago reports  (zvn_asterisk → callsprepago)
# ---------------------------------------------------------------------------


@legacy_bp.route("/alotarot.php")
@login_required_modal
def alotarot():
    """Alotarot prepago — October 2025, ddi 56222301555 / 1555."""
    logger.debug("legacy: alotarot requested")
    try:
        data = _fetch_prepago_ddi(2025, 10, (56222301555, 1555))
    except Exception as exc:
        return _db_error(exc)
    return render_template(
        "legacy/prepago_monthly.html",
        title="ALOTAROT",
        col_label="56222301555, 1555",
        **data,
    )


@legacy_bp.route("/pedromaritza.php")
@login_required_modal
def pedromaritza():
    """Pedro/Maritza prepago — February 2024, ssi 7012 / 6001 / 7013 / 8012."""
    logger.debug("legacy: pedromaritza requested")
    try:
        data = _fetch_prepago_ssi(2024, 2, (7012, 6001, 7013, 8012))
    except Exception as exc:
        return _db_error(exc)
    return render_template(
        "legacy/prepago_monthly.html",
        title="Pedro / Maritza",
        col_label="7012, 6001, 7013, 8012",
        **data,
    )
