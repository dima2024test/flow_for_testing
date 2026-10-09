from flowlib import Flow, R, D
from common import log_fault, PFX

START = "2026-10-12"


def overdue_digest():
    f = Flow("SCH_Daily_Overdue_Task_Digest", "SCH Daily Overdue Task Digest", "sch",
             "Daily batch (no object): collects overdue open Tasks, sorts by due date, escalates those overdue 14+ days to High, "
             "builds a digest of the oldest 50 and stores/e-mails it.")
    f.var("varTask", "SObject", obj="Task")
    f.var("colToUpdate", "SObject", coll=True, obj="Task")
    f.var("varTotal", "Number", scale=0, default=0)
    f.var("varEscalated", "Number", scale=0, default=0)
    f.var("varList", "String", default="")
    f.formula("fxCutoff14", "Date", "TODAY() - 14")
    f.formula("fxLine", "String", "LEFT({!varTask.Subject}, 80) & ' (due ' & TEXT({!varTask.ActivityDate}) & ')'")
    f.tt("ttDigest", "Overdue tasks: {!varTotal}\nEscalated to High (14+ days): {!varEscalated}\n\nOldest items:\n{!varList}")
    f.get("Get_Overdue_Tasks", "Task", [("IsClosed", "EqualTo", False), ("ActivityDate", "LessThan", R("$Flow.CurrentDate"))], "Asg_Total", "Log_Fault")
    f.assign("Asg_Total", [("varTotal", "AssignCount", R("Get_Overdue_Tasks"))], "Dec_Any_Overdue")
    f.decision("Dec_Any_Overdue", [("Has_Overdue", [("varTotal", "GreaterThan", 0)], "Sort_By_Due_Date")], None, "Nothing Overdue")
    f.sort_coll("Sort_By_Due_Date", "Get_Overdue_Tasks", "ActivityDate", "Asc", "Loop_Overdue", limit=50)
    f.loop("Loop_Overdue", "Get_Overdue_Tasks", "Asg_Append_Line", "Dec_Has_Escalations", var="varTask")
    f.assign("Asg_Append_Line", [("varList", "Add", R("fxLine")), ("varList", "Add", "; ")], "Dec_Very_Old")
    f.decision("Dec_Very_Old", [("Very_Old", [("varTask.ActivityDate", "LessThan", R("fxCutoff14")), ("varTask.Priority", "NotEqualTo", "High")], "Asg_Escalate")],
               "Loop_Overdue", "Recent")
    f.assign("Asg_Escalate", [("varTask.Priority", "Assign", "High"), ("colToUpdate", "Add", R("varTask")), ("varEscalated", "Add", 1)], "Loop_Overdue")
    f.decision("Dec_Has_Escalations", [("Has_Escalations", [("varEscalated", "GreaterThan", 0)], "Update_Tasks")], "Create_Digest_Task", "None")
    f.update("Update_Tasks", input_ref="colToUpdate", nxt="Create_Digest_Task", fault="Log_Fault")
    f.create("Create_Digest_Task", "Task", {"Subject": PFX + "Daily overdue task digest", "Description": R("ttDigest"), "Priority": "Normal",
                                            "Status": "Completed", "ActivityDate": R("$Flow.CurrentDate")}, "Send_Digest_Email", "Log_Fault")
    f.email("Send_Digest_Email", R("$User.Email"), PFX + "Daily overdue task digest", R("ttDigest"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Overdue_Tasks", trigger="Scheduled", schedule=("Daily", START, "04:00:00.000Z"))
    return f


def contract_expiry():
    f = Flow("SCH_Weekly_Contract_Expiry_Check", "SCH Weekly Contract Expiry Check", "sch",
             "Weekly, per activated Contract: contracts ending within 60 days get a renewal Opportunity (de-duplicated) and a Task; "
             "the first account contact with an e-mail is attached; expired contracts get a clean-up Task.")
    f.var("varContactId", "String")
    f.formula("fxIn60Days", "Date", "TODAY() + 60")
    f.formula("fxRenewalName", "String", f"LEFT('{PFX}Renewal - ' & {{!$Record.ContractNumber}}, 120)")
    f.decision("Dec_Expiry_Window", [
        ("Expired", [("$Record.EndDate", "LessThan", R("$Flow.CurrentDate"))], "Create_Expired_Task"),
        ("Expiring_Soon", [("$Record.EndDate", "LessThanOrEqualTo", R("fxIn60Days"))], "Get_Existing_Renewal")],
        None, "Not Yet")
    f.create("Create_Expired_Task", "Task", {"Subject": PFX + "Contract past end date - update status", "WhatId": R("$Record.Id"),
                                             "OwnerId": R("$Record.OwnerId"), "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    f.get("Get_Existing_Renewal", "Opportunity", [("AccountId", "EqualTo", R("$Record.AccountId")), ("Name", "EqualTo", R("fxRenewalName"))],
          "Dec_Renewal_Exists", "Log_Fault", first=True)
    f.decision("Dec_Renewal_Exists", [("Exists", [("Get_Existing_Renewal", "IsNull", False)], None)], "Get_Account_Contacts", "Create Renewal")
    f.get("Get_Account_Contacts", "Contact", [("AccountId", "EqualTo", R("$Record.AccountId"))], "Loop_Contacts", "Log_Fault", sort="CreatedDate")
    f.loop("Loop_Contacts", "Get_Account_Contacts", "Dec_Usable_Contact", "Create_Renewal_Opportunity")
    f.decision("Dec_Usable_Contact", [("Usable", [("varContactId", "IsNull", True), ("Loop_Contacts.Email", "IsNull", False)], "Asg_Contact")],
               "Loop_Contacts", "Skip")
    f.assign("Asg_Contact", [("varContactId", "Assign", R("Loop_Contacts.Id"))], "Loop_Contacts")
    f.create("Create_Renewal_Opportunity", "Opportunity", {"Name": R("fxRenewalName"), "AccountId": R("$Record.AccountId"), "StageName": "Prospecting",
                                                           "CloseDate": R("$Record.EndDate"), "OwnerId": R("$Record.OwnerId"),
                                                           "Type": "Existing Customer - Upgrade"}, "Create_Renewal_Task", "Log_Fault")
    f.create("Create_Renewal_Task", "Task", {"Subject": PFX + "Start contract renewal", "WhatId": R("Create_Renewal_Opportunity"), "WhoId": R("varContactId"),
                                             "OwnerId": R("$Record.OwnerId"), "ActivityDate": R("$Flow.CurrentDate"), "Priority": "High",
                                             "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Expiry_Window", obj="Contract", trigger="Scheduled", filters=[("Status", "EqualTo", "Activated")],
            schedule=("Weekly", START, "05:30:00.000Z"))
    return f


def inactive_accounts():
    f = Flow("SCH_Weekly_Inactive_Account_Review", "SCH Weekly Inactive Account Review", "sch",
             "Weekly, per customer Account not modified for 180 days: no open deals or cases -> rating Cold + review Task; open deals -> "
             "re-engagement Task with pipeline numbers from subflow.")
    f.var("varOpenOpps", "Number", scale=0, default=0)
    f.var("varOpenCases", "Number", scale=0, default=0)
    f.var("varPipeline", "Currency", scale=2)
    f.formula("fxStaleCutoff", "DateTime", "NOW() - 180")
    f.tt("ttReengage", "Account {!$Record.Name} has not been updated for 180+ days but still has {!varOpenOpps} open deal(s) worth {!varPipeline}.")
    f.decision("Dec_Stale", [("Stale", [("$Record.LastModifiedDate", "LessThan", R("fxStaleCutoff"))], "Get_Open_Opportunities")], None, "Recently Active")
    f.get("Get_Open_Opportunities", "Opportunity", [("AccountId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False)], "Asg_Opp_Count", "Log_Fault")
    f.assign("Asg_Opp_Count", [("varOpenOpps", "AssignCount", R("Get_Open_Opportunities"))], "Get_Open_Cases")
    f.get("Get_Open_Cases", "Case", [("AccountId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False)], "Asg_Case_Count", "Log_Fault")
    f.assign("Asg_Case_Count", [("varOpenCases", "AssignCount", R("Get_Open_Cases"))], "Dec_Activity")
    f.decision("Dec_Activity", [
        ("Has_Open_Deals", [("varOpenOpps", "GreaterThan", 0)], "Sub_Pipeline_Summary"),
        ("Nothing_Open", [("varOpenCases", "EqualTo", 0)], "Dec_Already_Cold")], None, "Only Cases")
    f.subflow("Sub_Pipeline_Summary", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("$Record.Id"), "inCreateTask": False},
              {"outTotalPipeline": "varPipeline"}, "Create_Reengage_Task")
    f.create("Create_Reengage_Task", "Task", {"Subject": PFX + "Re-engage inactive account with open deals", "WhatId": R("$Record.Id"),
                                              "OwnerId": R("$Record.OwnerId"), "Description": R("ttReengage"), "Priority": "Normal",
                                              "Status": "Not Started"}, None, "Log_Fault")
    f.decision("Dec_Already_Cold", [("Already_Cold", [("$Record.Rating", "EqualTo", "Cold")], None)], "Update_Account_Cold", "Not Cold")
    f.update("Update_Account_Cold", "Account", [("Id", "EqualTo", R("$Record.Id"))], {"Rating": "Cold"}, "Create_Review_Task", "Log_Fault")
    f.create("Create_Review_Task", "Task", {"Subject": PFX + "Review dormant account", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                            "Priority": "Low", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Stale", obj="Account", trigger="Scheduled", filters=[("Type", "EqualTo", "Customer - Direct"), ("Type", "EqualTo", "Customer - Channel")], filter_logic="or",
            schedule=("Weekly", START, "04:30:00.000Z"))
    return f


def case_sla():
    f = Flow("SCH_Daily_Case_SLA_Monitor", "SCH Daily Case SLA Monitor", "sch",
             "Daily, per open High/Medium Case: New cases older than 24h get an SLA Task (de-duplicated) for the owning user; cases "
             "older than 72h are set to Escalated and e-mailed.")
    f.var("varOwnerId", "String")
    f.formula("fxAge24", "DateTime", "NOW() - 1")
    f.formula("fxAge72", "DateTime", "NOW() - 3")
    f.tt("ttBreach", "Case {!$Record.CaseNumber} ({!$Record.Priority}) has been open since {!$Record.CreatedDate} and was escalated by the SLA monitor.")
    f.decision("Dec_Case_Age", [
        ("Over_72h", [("$Record.CreatedDate", "LessThan", R("fxAge72")), ("$Record.Status", "NotEqualTo", "Escalated")], "Update_Case_Escalated"),
        ("Over_24h_New", [("$Record.CreatedDate", "LessThan", R("fxAge24")), ("$Record.Status", "EqualTo", "New")], "Get_Owner_User")],
        None, "Within SLA")
    f.update("Update_Case_Escalated", "Case", [("Id", "EqualTo", R("$Record.Id"))], {"Status": "Escalated"}, "Send_Breach_Email", "Log_Fault")
    f.email("Send_Breach_Email", R("$User.Email"), PFX + "Case SLA breach (72h)", R("ttBreach"), None, "Log_Fault")
    f.get("Get_Owner_User", "User", [("Id", "EqualTo", R("$Record.OwnerId")), ("IsActive", "EqualTo", True)], "Dec_Owner_Is_User", "Log_Fault", first=True)
    f.decision("Dec_Owner_Is_User", [("Is_User", [("Get_Owner_User", "IsNull", False)], "Asg_Owner_User")], "Asg_Owner_Creator", "Queue or Inactive")
    f.assign("Asg_Owner_User", [("varOwnerId", "Assign", R("Get_Owner_User.Id"))], "Get_Existing_SLA_Task")
    f.assign("Asg_Owner_Creator", [("varOwnerId", "Assign", R("$Record.CreatedById"))], "Get_Existing_SLA_Task")
    f.get("Get_Existing_SLA_Task", "Task", [("WhatId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False),
                                            ("Subject", "EqualTo", PFX + "Case waiting 24h+ in New")], "Dec_Task_Exists", "Log_Fault", first=True)
    f.decision("Dec_Task_Exists", [("Exists", [("Get_Existing_SLA_Task", "IsNull", False)], None)], "Create_SLA_Task", "No Task")
    f.create("Create_SLA_Task", "Task", {"Subject": PFX + "Case waiting 24h+ in New", "WhatId": R("$Record.Id"), "OwnerId": R("varOwnerId"),
                                         "ActivityDate": R("$Flow.CurrentDate"), "Priority": "High", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Case_Age", obj="Case", trigger="Scheduled", filters=[("IsClosed", "EqualTo", False), ("Priority", "NotEqualTo", "Low")],
            schedule=("Daily", START, "07:00:00.000Z"))
    return f


def pipeline_snapshot():
    f = Flow("SCH_Weekly_Pipeline_Snapshot", "SCH Weekly Pipeline Snapshot", "sch",
             "Weekly batch (no object): totals all open Opportunities, counts deals closing within 30 days and past due, lists the top 10 "
             "deals by amount, stores the snapshot as a Task and e-mails it.")
    f.var("varOpp", "SObject", obj="Opportunity")
    f.var("varTotal", "Currency", scale=2, default=0)
    f.var("varCount", "Number", scale=0, default=0)
    f.var("varPastDue", "Number", scale=0, default=0)
    f.var("varTopList", "String", default="")
    f.var("varTop", "SObject", obj="Opportunity")
    f.formula("fxIn30Days", "Date", "TODAY() + 30")
    f.formula("fxAmount", "Currency", "BLANKVALUE({!varOpp.Amount}, 0)", scale=2)
    f.formula("fxTopLine", "String", "LEFT({!varTop.Name}, 60) & ': ' & TEXT(BLANKVALUE({!varTop.Amount}, 0))")
    f.tt("ttSnapshot", "Weekly pipeline snapshot ({!$Flow.CurrentDate})\nOpen deals: {!varCount}\nTotal amount: {!varTotal}\n"
                       "Closing within 30 days: {!varClosingSoon}\nPast due: {!varPastDue}\n\nTop 10 deals:\n{!varTopList}")
    f.var("varClosingSoon", "Number", scale=0, default=0)
    f.get("Get_Open_Opportunities", "Opportunity", [("IsClosed", "EqualTo", False)], "Asg_Count", "Log_Fault")
    f.assign("Asg_Count", [("varCount", "AssignCount", R("Get_Open_Opportunities"))], "Dec_Any_Open")
    f.decision("Dec_Any_Open", [("Has_Open", [("varCount", "GreaterThan", 0)], "Loop_All_Deals")], "Create_Snapshot_Task", "No Pipeline")
    f.loop("Loop_All_Deals", "Get_Open_Opportunities", "Asg_Totals", "Filter_Closing_Soon", var="varOpp")
    f.assign("Asg_Totals", [("varTotal", "Add", R("fxAmount"))], "Dec_Past_Due")
    f.decision("Dec_Past_Due", [("Past_Due", [("varOpp.CloseDate", "LessThan", R("$Flow.CurrentDate"))], "Asg_Past_Due")], "Loop_All_Deals", "On Track")
    f.assign("Asg_Past_Due", [("varPastDue", "Add", 1)], "Loop_All_Deals")
    f.filter_coll("Filter_Closing_Soon", "Get_Open_Opportunities", "Opportunity",
                  [("CloseDate", "GreaterThanOrEqualTo", R("$Flow.CurrentDate")), ("CloseDate", "LessThanOrEqualTo", R("fxIn30Days"))], "Asg_Closing_Soon")
    f.assign("Asg_Closing_Soon", [("varClosingSoon", "AssignCount", R("Filter_Closing_Soon"))], "Sort_By_Amount")
    f.sort_coll("Sort_By_Amount", "Get_Open_Opportunities", "Amount", "Desc", "Loop_Top_Deals", limit=10)
    f.loop("Loop_Top_Deals", "Get_Open_Opportunities", "Asg_Top_Line", "Create_Snapshot_Task", var="varTop")
    f.assign("Asg_Top_Line", [("varTopList", "Add", R("fxTopLine")), ("varTopList", "Add", "; ")], "Loop_Top_Deals")
    f.create("Create_Snapshot_Task", "Task", {"Subject": PFX + "Weekly pipeline snapshot", "Description": R("ttSnapshot"), "Priority": "Low",
                                              "Status": "Completed", "ActivityDate": R("$Flow.CurrentDate")}, "Send_Snapshot_Email", "Log_Fault")
    f.email("Send_Snapshot_Email", R("$User.Email"), PFX + "Weekly pipeline snapshot", R("ttSnapshot"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Open_Opportunities", trigger="Scheduled", schedule=("Weekly", START, "06:30:00.000Z"))
    return f


ALL = [overdue_digest, contract_expiry, inactive_accounts, case_sla, pipeline_snapshot]
