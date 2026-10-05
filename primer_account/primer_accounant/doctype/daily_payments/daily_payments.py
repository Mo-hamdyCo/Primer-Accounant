import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form, nowdate

from primer_account.primer_accounant.doctype.payment_transactions.payment_transactions import (
    get_row_account,
)

ROWS = "transaction"  # fieldname الجدول الفرعي
ITEM = "items"  # fieldname الصنف في الصف


def get_default_company():
    return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
        "Global Defaults", "default_company"
    )


@frappe.whitelist()
def get_mop_account(mode_of_payment, company):
    return frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account",
    )


class DailyPayments(Document):
    @property
    def _company(self):
        return self.get("company") or get_default_company()

    def validate(self):
        self.set_cash_account()
        self.validate_and_set_rows()
        self.calculate_total()

    def set_cash_account(self):
        if not self._company:
            frappe.throw(_("Default Company is not set"))

        self.account = get_mop_account(self.mode_of_payment, self._company)
        if not self.account:
            frappe.throw(
                _("No default account for Mode of Payment {0} in Company {1}").format(
                    frappe.bold(self.mode_of_payment), frappe.bold(self._company)
                )
            )

    def validate_and_set_rows(self):
        rows = self.get(ROWS)
        if not rows:
            frappe.throw(_("Please add at least one transaction"))

        for row in rows:
            if flt(row.get("amount")) <= 0:
                frappe.throw(_("Row #{0}: Amount must be greater than zero").format(row.idx))

            if row.payment_type == "Supplier" and not row.supplier:
                frappe.throw(_("Row #{0}: Supplier is required").format(row.idx))

            row.account = get_row_account(
                row.payment_type, self._company, row.get(ITEM), row.supplier
            )
            if not row.account:
                frappe.throw(
                    _("Row #{0}: Could not determine account. Check Item/Company defaults.").format(row.idx)
                )

            if row.account == self.account:
                frappe.throw(_("Row #{0}: Account cannot be the same as the cash account").format(row.idx))

            if row.payment_type == "Expense":
                row.supplier = None
            else:
                row.set(ITEM, None)

    def calculate_total(self):
        self.amount = flt(
            sum(flt(r.get("amount")) for r in self.get(ROWS)), self.precision("amount")
        )

    def on_submit(self):
        je = self.make_journal_entry()
        self.db_set("jl_reference", je.name)
        frappe.msgprint(
            _("Draft Journal Entry {0} created").format(get_link_to_form("Journal Entry", je.name)),
            indicator="green",
        )

    def make_journal_entry(self):
        company = self._company
        company_cc = frappe.get_cached_value("Company", company, "cost_center")
        is_cash = frappe.db.get_value("Account", self.account, "account_type") == "Cash"

        je = frappe.new_doc("Journal Entry")
        je.update(
            {
                "voucher_type": "Cash Entry" if is_cash else "Journal Entry",
                "company": company,
                "posting_date": self.get("posting_date") or nowdate(),
                "user_remark": _("Daily Payments {0}").format(self.name),
            }
        )

        # المدين: المصروف / المورد
        for row in self.get(ROWS):
            line = {
                "account": row.account,
                "debit_in_account_currency": flt(row.get("amount")),
                "user_remark": row.get("remarks"),
            }
            if row.payment_type == "Supplier":
                line.update({"party_type": "Supplier", "party": row.supplier})
            else:
                line["cost_center"] = row.get("cost_center") or company_cc
            je.append("accounts", line)

        # الدائن: الخزينة
        je.append(
            "accounts",
            {
                "account": self.account,
                "credit_in_account_currency": flt(self.amount),
                "cost_center": company_cc,
            },
        )

        je.insert()  # بيفضل Draft
        return je

    def on_cancel(self):
        je_name = self.jl_reference
        if not je_name:
            return
        self.db_set("jl_reference", None)
        je = frappe.get_doc("Journal Entry", je_name)
        if je.docstatus == 0:
            frappe.delete_doc("Journal Entry", je_name)
        elif je.docstatus == 1:
            je.cancel()