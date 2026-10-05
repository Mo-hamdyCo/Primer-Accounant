import json

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    validate_filters(filters)

    accounts = get_accounts(filters)
    if not accounts:
        return get_columns(filters), []

    opening = get_opening_balances(filters, accounts)
    entries = get_gl_entries(filters, accounts)
    if filters.get("include_pending"):
        entries += get_pending_entries(filters, accounts)

    set_daily_payment_refs(entries)
    entries.sort(key=lambda e: (e.account, str(e.posting_date), e.pending))  # stable sort

    return get_columns(filters), build_data(filters, accounts, opening, entries)


def validate_filters(filters):
    if not filters.company:
        frappe.throw(_("Company is required"))
    if not (filters.from_date and filters.to_date):
        frappe.throw(_("From Date and To Date are required"))
    if getdate(filters.from_date) > getdate(filters.to_date):
        frappe.throw(_("From Date cannot be after To Date"))


def parse_list(value):
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = [value]
    return value if isinstance(value, list) else [value]


def get_accounts(filters):
    conds = {
        "company": filters.company,
        "account_type": ["in", ["Cash", "Bank"]],
        "is_group": 0,
    }
    selected = parse_list(filters.get("account"))
    if selected:
        conds["name"] = ["in", selected]
    return frappe.get_all("Account", filters=conds, pluck="name", order_by="name")


def get_opening_balances(filters, accounts):
    rows = frappe.db.sql(
        """
        select account, sum(debit - credit)
        from `tabGL Entry`
        where company = %s and is_cancelled = 0
            and account in %s and posting_date < %s
        group by account
        """,
        (filters.company, tuple(accounts), filters.from_date),
    )
    return dict(rows)


def get_gl_entries(filters, accounts):
    return frappe.db.sql(
        """
        select posting_date, account, debit, credit, voucher_type, voucher_no,
            against, party_type, party, remarks, 0 as pending
        from `tabGL Entry`
        where company = %(company)s and is_cancelled = 0
            and account in %(accounts)s
            and posting_date between %(from_date)s and %(to_date)s
        order by posting_date, creation
        """,
        {
            "company": filters.company,
            "accounts": tuple(accounts),
            "from_date": filters.from_date,
            "to_date": filters.to_date,
        },
        as_dict=True,
    )


def get_pending_entries(filters, accounts):
    """Draft JEs created from submitted Daily Payments. Not in GL yet, so no duplication."""
    return frappe.db.sql(
        """
        select je.posting_date, jea.account, jea.debit, jea.credit,
            'Journal Entry' as voucher_type, je.name as voucher_no,
            jea.against_account as against, jea.party_type, jea.party,
            jea.user_remark as remarks, 1 as pending
        from `tabJournal Entry Account` jea
        inner join `tabJournal Entry` je on je.name = jea.parent
        where je.docstatus = 0 and je.company = %(company)s
            and jea.account in %(accounts)s
            and je.posting_date between %(from_date)s and %(to_date)s
            and je.name in (
                select jl_reference from `tabDaily Payments`
                where docstatus = 1 and ifnull(jl_reference, '') != ''
            )
        """,
        {
            "company": filters.company,
            "accounts": tuple(accounts),
            "from_date": filters.from_date,
            "to_date": filters.to_date,
        },
        as_dict=True,
    )


def set_daily_payment_refs(entries):
    vouchers = list({e.voucher_no for e in entries if e.voucher_type == "Journal Entry"})
    mapping = {}
    if vouchers:
        mapping = dict(
            frappe.get_all(
                "Daily Payments",
                filters={"jl_reference": ["in", vouchers], "docstatus": 1},
                fields=["jl_reference", "name"],
                as_list=True,
            )
        )
    for e in entries:
        e.daily_payment = mapping.get(e.voucher_no)
        e.status = _("Pending (Draft JE)") if e.pending else _("Posted")


def consolidate(rows):
    out = {}
    for r in rows:
        key = (str(r.posting_date), r.pending)
        d = out.setdefault(
            key,
            frappe._dict(
                account=r.account,
                posting_date=r.posting_date,
                pending=r.pending,
                status=r.status,
                debit=0,
                credit=0,
                _vouchers=set(),
            ),
        )
        d.debit += flt(r.debit)
        d.credit += flt(r.credit)
        d._vouchers.add(r.voucher_no)
    result = list(out.values())
    for d in result:
        d.vouchers = len(d.pop("_vouchers"))
    return result


def build_data(filters, accounts, opening, entries):
    by_account = {}
    for e in entries:
        by_account.setdefault(e.account, []).append(e)

    data = []
    g_dr = g_cr = g_close = 0

    for acc in accounts:
        rows = by_account.get(acc, [])
        open_bal = flt(opening.get(acc))
        if not rows and not open_bal:
            continue

        if filters.get("consolidated"):
            rows = consolidate(rows)

        balance = open_bal
        t_dr = t_cr = 0
        data.append({"account": acc, "voucher_type": _("Opening Balance"), "balance": balance})

        for r in rows:
            dr, cr = flt(r.debit), flt(r.credit)
            balance += dr - cr
            t_dr += dr
            t_cr += cr
            r["balance"] = balance
            data.append(r)

        data.append({"account": "'" + _("Total") + "'", "debit": t_dr, "credit": t_cr})
        data.append({"account": "'" + _("Closing (Dr - Cr)") + "'", "balance": balance})
        data.append({})

        g_dr += t_dr
        g_cr += t_cr
        g_close += balance

    if data:
        data.append({"account": "'" + _("Grand Total") + "'", "debit": g_dr, "credit": g_cr, "balance": g_close})
    return data


def get_columns(filters):
    cols = [
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
        {"label": _("Account"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 220},
        {"label": _("Debit"), "fieldname": "debit", "fieldtype": "Currency", "width": 110},
        {"label": _("Credit"), "fieldname": "credit", "fieldtype": "Currency", "width": 110},
        {"label": _("Balance"), "fieldname": "balance", "fieldtype": "Currency", "width": 120},
    ]
    if filters.get("consolidated"):
        cols.append({"label": _("Vouchers"), "fieldname": "vouchers", "fieldtype": "Int", "width": 80})
    else:
        cols += [
            {"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 130},
            {"label": _("Voucher No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 150},
            {"label": _("Daily Payment"), "fieldname": "daily_payment", "fieldtype": "Link", "options": "Daily Payments", "width": 140},
            {"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "width": 90},
            {"label": _("Party"), "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 150},
            {"label": _("Against"), "fieldname": "against", "fieldtype": "Data", "width": 200},
        ]
    cols.append({"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120})
    if not filters.get("consolidated"):
        cols.append({"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 250})
    return cols