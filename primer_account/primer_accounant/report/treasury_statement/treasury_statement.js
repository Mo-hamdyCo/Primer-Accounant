frappe.query_reports["Treasury Statement"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company"),
    },
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.month_start(),
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.get_today(),
    },
    {
      fieldname: "account",
      label: __("Account"),
      fieldtype: "MultiSelectList",
      get_data: function (txt) {
        return frappe.db.get_link_options("Account", txt, {
          company: frappe.query_report.get_filter_value("company"),
          account_type: ["in", ["Cash", "Bank"]],
          is_group: 0,
        });
      },
    },
    {
      fieldname: "consolidated",
      label: __("Consolidated (Daily Summary)"),
      fieldtype: "Check",
    },
    {
      fieldname: "include_pending",
      label: __("Include Pending (Draft JE)"),
      fieldtype: "Check",
    },
  ],
};