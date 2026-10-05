const ROW_ACCOUNT =
  "primer_account.primer_accounant.doctype.payment_transactions.payment_transactions.get_row_account";
const MOP_ACCOUNT =
  "primer_account.primer_accounant.doctype.daily_payments.daily_payments.get_mop_account";

const ROWS = "transaction";
const ITEM = "items";

function get_company(frm) {
  return frm.doc.company || frappe.defaults.get_user_default("Company");
}

frappe.ui.form.on("Daily Payments", {
  refresh(frm) {
    frm.set_df_property("account", "read_only", 1);
    frm.set_df_property("amount", "read_only", 1);
  },
  mode_of_payment(frm) {
    set_cash_account(frm);
  },
  [`${ROWS}_remove`](frm) {
    calculate_total(frm);
  },
});

frappe.ui.form.on("Payment Transactions", {
  payment_type(frm, cdt, cdn) {
    frappe.model.set_value(cdt, cdn, { [ITEM]: null, supplier: null, account: null });
  },
  [ITEM](frm, cdt, cdn) {
    set_row_account(frm, cdt, cdn);
  },
  supplier(frm, cdt, cdn) {
    set_row_account(frm, cdt, cdn);
  },
  amount(frm) {
    calculate_total(frm);
  },
});

function set_cash_account(frm) {
  const company = get_company(frm);
  if (!frm.doc.mode_of_payment || !company) return;
  frappe.call({
    method: MOP_ACCOUNT,
    args: { mode_of_payment: frm.doc.mode_of_payment, company },
    callback: (r) => {
      frm.set_value("account", r.message || null);
      if (!r.message) {
        frappe.msgprint(__("No default account set for this Mode of Payment in {0}", [company]));
      }
    },
  });
}

function set_row_account(frm, cdt, cdn) {
  const row = locals[cdt][cdn];
  const company = get_company(frm);
  if (!company || !row.payment_type) return;
  frappe.call({
    method: ROW_ACCOUNT,
    args: {
      payment_type: row.payment_type,
      company,
      item: row[ITEM],
      supplier: row.supplier,
    },
    callback: (r) => frappe.model.set_value(cdt, cdn, "account", r.message || null),
  });
}

function calculate_total(frm) {
  const total = (frm.doc[ROWS] || []).reduce((s, r) => s + flt(r.amount), 0);
  frm.set_value("amount", total);
}