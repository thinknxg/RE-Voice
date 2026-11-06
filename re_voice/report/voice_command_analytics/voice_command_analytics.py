"""Which voice commands are used, how well they resolve, and what they cost."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    conditions = ["1=1"]
    values = {}
    if filters.get("from_date"):
        conditions.append("DATE(vi.creation) >= %(from_date)s")
        values["from_date"] = filters.from_date
    if filters.get("to_date"):
        conditions.append("DATE(vi.creation) <= %(to_date)s")
        values["to_date"] = filters.to_date
    if filters.get("agent"):
        conditions.append("vi.agent = %(agent)s")
        values["agent"] = filters.agent

    rows = frappe.db.sql(f"""
        SELECT IFNULL(vi.command, '(unrecognised)') AS command,
               COUNT(*) AS attempts,
               SUM(CASE WHEN vi.status = 'Executed' THEN 1 ELSE 0 END) AS executed,
               SUM(CASE WHEN vi.status IN ('Failed', 'Unrecognised') THEN 1 ELSE 0 END)
                   AS failed,
               SUM(CASE WHEN vi.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled,
               SUM(CASE WHEN vi.resolver = 'Keyword' THEN 1 ELSE 0 END) AS by_keyword,
               SUM(CASE WHEN vi.resolver = 'LLM' THEN 1 ELSE 0 END) AS by_llm,
               AVG(vi.confidence) AS avg_confidence
        FROM `tabVoice Intent` vi
        WHERE {' AND '.join(conditions)}
        GROUP BY IFNULL(vi.command, '(unrecognised)')
        ORDER BY attempts DESC
    """, values, as_dict=True)

    for row in rows:
        row["success_rate"] = flt(row.executed * 100 / row.attempts, 1) \
            if row.attempts else 0
        row["keyword_share"] = flt(row.by_keyword * 100 / row.attempts, 1) \
            if row.attempts else 0
        row["avg_confidence"] = flt(row.avg_confidence, 2)

    total = sum(r.attempts for r in rows) or 0
    keyword_total = sum(r.by_keyword for r in rows)
    executed = sum(r.executed for r in rows)
    ai_cost = frappe.db.sql("SELECT COALESCE(SUM(cost), 0) FROM `tabVoice Usage Log`")[0][0]

    summary = [
        {"label": _("Commands Issued"), "value": total, "datatype": "Int"},
        {"label": _("Success Rate"), "datatype": "Percent",
         "value": flt(executed * 100 / total, 1) if total else 0,
         "indicator": "Green" if total and executed / total > 0.8 else "Orange"},
        {"label": _("Resolved Without LLM"), "datatype": "Percent",
         "value": flt(keyword_total * 100 / total, 1) if total else 0},
        {"label": _("AI Spend"), "value": flt(ai_cost, 3), "datatype": "Currency"},
    ]
    chart = {"data": {"labels": [r.command for r in rows[:10]],
                      "datasets": [{"name": _("Attempts"),
                                    "values": [r.attempts for r in rows[:10]]}]},
             "type": "bar"}
    return get_columns(), rows, None, chart, summary


def get_columns():
    return [
        {"label": _("Command"), "fieldname": "command", "fieldtype": "Data",
         "width": 190},
        {"label": _("Attempts"), "fieldname": "attempts", "fieldtype": "Int",
         "width": 90},
        {"label": _("Executed"), "fieldname": "executed", "fieldtype": "Int",
         "width": 90},
        {"label": _("Success %"), "fieldname": "success_rate", "fieldtype": "Percent",
         "width": 100},
        {"label": _("Failed"), "fieldname": "failed", "fieldtype": "Int", "width": 80},
        {"label": _("Cancelled"), "fieldname": "cancelled", "fieldtype": "Int",
         "width": 95},
        {"label": _("Keyword %"), "fieldname": "keyword_share", "fieldtype": "Percent",
         "width": 100, "description": "Resolved by the free tier"},
        {"label": _("Via LLM"), "fieldname": "by_llm", "fieldtype": "Int", "width": 85},
        {"label": _("Avg Confidence"), "fieldname": "avg_confidence",
         "fieldtype": "Float", "width": 120},
    ]
