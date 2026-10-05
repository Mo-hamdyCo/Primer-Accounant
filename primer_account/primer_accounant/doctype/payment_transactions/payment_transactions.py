import frappe
from frappe.model.document import Document
from erpnext.accounts.party import get_party_account


class PaymentTransactions(Document):
    pass


def get_item_expense_account(item, company):
    account = frappe.db.get_value(
        "Item Default",
        {"parent": item, "parenttype": "Item", "company": company},
        "expense_account",
    )
    if not account:
        item_group = frappe.db.get_value("Item", item, "item_group")
        account = frappe.db.get_value(
            "Item Default",
            {"parent": item_group, "parenttype": "Item Group", "company": company},
            "expense_account",
        )
    return account or frappe.get_cached_value("Company", company, "default_expense_account")


@frappe.whitelist()
def get_row_account(payment_type, company, item=None, supplier=None):
    if payment_type == "Expense":
        if item:
            return get_item_expense_account(item, company)
        return frappe.get_cached_value("Company", company, "default_expense_account")

    if payment_type == "Supplier":
        if not supplier:
            return None
        return get_party_account("Supplier", supplier, company)

    return None