from flowlib import Flow, R, D
from common import log_fault, PFX


def pipeline_summary():
    f = Flow("AUT_Opportunity_Pipeline_Summary", "AUT Opportunity Pipeline Summary", "auto",
             "Returns open pipeline, weighted pipeline, deal count and the largest open deal for an Account; optionally writes a summary Task.")
    f.var("inAccountId", "String", inp=True)
    f.var("inCreateTask", "Boolean", inp=True, default=False)
    f.var("outTotalPipeline", "Currency", out=True, scale=2, default=0)
    f.var("outWeightedPipeline", "Currency", out=True, scale=2, default=0)
    f.var("outDealCount", "Number", out=True, scale=0, default=0)
    f.var("outLateStageCount", "Number", out=True, scale=0, default=0)
    f.var("outTopDealName", "String", out=True)
    f.var("varOpp", "SObject", obj="Opportunity")
    f.formula("fxAmount", "Currency", "BLANKVALUE({!varOpp.Amount}, 0)", scale=2)
    f.formula("fxWeighted", "Currency", "BLANKVALUE({!varOpp.Amount}, 0) * BLANKVALUE({!varOpp.Probability}, 0) / 100", scale=2)
    f.tt("ttSummary", "Open pipeline: {!outTotalPipeline}\nWeighted: {!outWeightedPipeline}\nDeals: {!outDealCount} (late stage: {!outLateStageCount})\n"
                      "Largest deal: {!outTopDealName}")
    f.get("Get_Open_Opportunities", "Opportunity", [("AccountId", "EqualTo", R("inAccountId")), ("IsClosed", "EqualTo", False)],
          "Asg_Deal_Count", "Log_Fault")
    f.assign("Asg_Deal_Count", [("outDealCount", "AssignCount", R("Get_Open_Opportunities"))], "Dec_Has_Deals")
    f.decision("Dec_Has_Deals", [("Has_Deals", [("outDealCount", "GreaterThan", 0)], "Sort_By_Amount")], "Asg_No_Deals", "No Deals")
    f.sort_coll("Sort_By_Amount", "Get_Open_Opportunities", "Amount", "Desc", "Loop_Opportunities")
    f.loop("Loop_Opportunities", "Get_Open_Opportunities", "Asg_Accumulate", "Dec_Create_Task", var="varOpp")
    f.assign("Asg_Accumulate", [("outTotalPipeline", "Add", R("fxAmount")), ("outWeightedPipeline", "Add", R("fxWeighted"))], "Dec_Top_Deal")
    f.decision("Dec_Top_Deal", [("First_Item", [("outTopDealName", "IsNull", True)], "Asg_Top_Deal")], "Dec_Late_Stage", "Not First")
    f.assign("Asg_Top_Deal", [("outTopDealName", "Assign", R("varOpp.Name"))], "Dec_Late_Stage")
    f.decision("Dec_Late_Stage", [("Late_Stage", [("varOpp.Probability", "GreaterThanOrEqualTo", 70)], "Asg_Late_Stage")], "Loop_Opportunities", "Early Stage")
    f.assign("Asg_Late_Stage", [("outLateStageCount", "Add", 1)], "Loop_Opportunities")
    f.decision("Dec_Create_Task", [("Task_Requested", [("inCreateTask", "EqualTo", True)], "Create_Summary_Task")], None, "No Task")
    f.create("Create_Summary_Task", "Task", {"Subject": PFX + "Pipeline summary", "WhatId": R("inAccountId"), "Description": R("ttSummary"),
                                             "Status": "Completed", "Priority": "Low", "ActivityDate": R("$Flow.CurrentDate")}, None, "Log_Fault")
    f.assign("Asg_No_Deals", [("outTotalPipeline", "Assign", 0), ("outTopDealName", "Assign", "none")])
    log_fault(f, record=R("inAccountId"))
    f.start("Get_Open_Opportunities")
    return f


def task_reassign():
    f = Flow("AUT_Task_Bulk_Reassign", "AUT Task Bulk Reassign", "auto",
             "Moves open Tasks from one user to another (optionally only High priority), validates the target user, bulk-updates and "
             "leaves an audit Task for the new owner.")
    f.var("inFromUserId", "String", inp=True)
    f.var("inToUserId", "String", inp=True)
    f.var("inHighOnly", "Boolean", inp=True, default=False)
    f.var("outMovedCount", "Number", out=True, scale=0, default=0)
    f.var("outResult", "String", out=True)
    f.var("varTask", "SObject", obj="Task")
    f.var("colSource", "SObject", coll=True, obj="Task")
    f.var("colToUpdate", "SObject", coll=True, obj="Task")
    f.tt("ttAudit", "{!outMovedCount} open task(s) were reassigned to you from user {!inFromUserId} by {!$User.Username}.")
    f.get("Get_Target_User", "User", [("Id", "EqualTo", R("inToUserId")), ("IsActive", "EqualTo", True)], "Dec_Target_Valid", "Log_Fault", first=True)
    f.decision("Dec_Target_Valid", [("Target_Active", [("Get_Target_User", "IsNull", False), ("inFromUserId", "NotEqualTo", R("inToUserId"))], "Get_Open_Tasks")],
               "Asg_Invalid_Target", "Invalid")
    f.get("Get_Open_Tasks", "Task", [("OwnerId", "EqualTo", R("inFromUserId")), ("IsClosed", "EqualTo", False)], "Dec_Priority_Mode", "Log_Fault")
    f.decision("Dec_Priority_Mode", [("High_Only", [("inHighOnly", "EqualTo", True)], "Filter_High_Priority")], "Asg_All_Tasks", "All Tasks")
    f.filter_coll("Filter_High_Priority", "Get_Open_Tasks", "Task", [("Priority", "EqualTo", "High")], "Asg_Filtered_Tasks")
    f.assign("Asg_Filtered_Tasks", [("colSource", "Assign", R("Filter_High_Priority"))], "Loop_Tasks")
    f.assign("Asg_All_Tasks", [("colSource", "Assign", R("Get_Open_Tasks"))], "Loop_Tasks")
    f.loop("Loop_Tasks", "colSource", "Asg_Change_Owner", "Dec_Anything_Moved", var="varTask")
    f.assign("Asg_Change_Owner", [("varTask.OwnerId", "Assign", R("inToUserId")), ("colToUpdate", "Add", R("varTask")), ("outMovedCount", "Add", 1)], "Loop_Tasks")
    f.decision("Dec_Anything_Moved", [("Moved", [("outMovedCount", "GreaterThan", 0)], "Update_Tasks")], "Asg_Nothing_Moved", "Nothing")
    f.update("Update_Tasks", input_ref="colToUpdate", nxt="Create_Audit_Task", fault="Log_Fault")
    f.create("Create_Audit_Task", "Task", {"Subject": PFX + "Tasks reassigned to you", "Description": R("ttAudit"), "OwnerId": R("inToUserId"),
                                           "Status": "Not Started", "Priority": "Normal", "ActivityDate": R("$Flow.CurrentDate")}, "Asg_Done", "Log_Fault")
    f.assign("Asg_Done", [("outResult", "Assign", "MOVED")])
    f.assign("Asg_Nothing_Moved", [("outResult", "Assign", "NOTHING_TO_MOVE")])
    f.assign("Asg_Invalid_Target", [("outResult", "Assign", "INVALID_TARGET")])
    log_fault(f)
    f.start("Get_Target_User")
    return f


def contact_snapshot():
    f = Flow("AUT_Contact_Activity_Snapshot", "AUT Contact Activity Snapshot", "auto",
             "Returns open/overdue task and open case counts for a Contact plus an engagement label; flags heavily overdue contacts with a Task.")
    f.var("inContactId", "String", inp=True)
    f.var("outOpenTasks", "Number", out=True, scale=0, default=0)
    f.var("outOverdueTasks", "Number", out=True, scale=0, default=0)
    f.var("outOpenCases", "Number", out=True, scale=0, default=0)
    f.var("outEngagement", "String", out=True)
    f.var("varTask", "SObject", obj="Task")
    f.tt("ttFlag", "Contact {!Get_Contact.Name} has {!outOverdueTasks} overdue task(s) and {!outOpenCases} open case(s).")
    f.get("Get_Contact", "Contact", [("Id", "EqualTo", R("inContactId"))], "Dec_Contact_Found", "Log_Fault", first=True)
    f.decision("Dec_Contact_Found", [("Found", [("Get_Contact", "IsNull", False)], "Get_Open_Tasks")], "Asg_Unknown", "Not Found")
    f.get("Get_Open_Tasks", "Task", [("WhoId", "EqualTo", R("inContactId")), ("IsClosed", "EqualTo", False)], "Loop_Tasks", "Log_Fault")
    f.loop("Loop_Tasks", "Get_Open_Tasks", "Asg_Count_Open", "Get_Open_Cases", var="varTask")
    f.assign("Asg_Count_Open", [("outOpenTasks", "Add", 1)], "Dec_Overdue")
    f.decision("Dec_Overdue", [("Overdue", [("varTask.ActivityDate", "LessThan", R("$Flow.CurrentDate"))], "Asg_Count_Overdue")], "Loop_Tasks", "On Time")
    f.assign("Asg_Count_Overdue", [("outOverdueTasks", "Add", 1)], "Loop_Tasks")
    f.get("Get_Open_Cases", "Case", [("ContactId", "EqualTo", R("inContactId")), ("IsClosed", "EqualTo", False)], "Asg_Case_Count", "Log_Fault")
    f.assign("Asg_Case_Count", [("outOpenCases", "AssignCount", R("Get_Open_Cases"))], "Dec_Engagement")
    f.decision("Dec_Engagement", [
        ("At_Risk", [("outOverdueTasks", "GreaterThanOrEqualTo", 3)], "Asg_At_Risk"),
        ("Active", [("outOpenTasks", "GreaterThan", 0)], "Asg_Active")], "Asg_Dormant", "Dormant")
    f.assign("Asg_At_Risk", [("outEngagement", "Assign", "AT_RISK")], "Create_Flag_Task")
    f.assign("Asg_Active", [("outEngagement", "Assign", "ACTIVE")])
    f.assign("Asg_Dormant", [("outEngagement", "Assign", "DORMANT")])
    f.create("Create_Flag_Task", "Task", {"Subject": PFX + "Contact has many overdue tasks", "WhoId": R("inContactId"), "Description": R("ttFlag"),
                                          "OwnerId": R("Get_Contact.OwnerId"), "Priority": "High", "Status": "Not Started"}, None, "Log_Fault")
    f.assign("Asg_Unknown", [("outEngagement", "Assign", "UNKNOWN")])
    log_fault(f, record=R("inContactId"))
    f.start("Get_Contact")
    return f


def lead_nurture():
    f = Flow("AUT_Lead_Nurture_With_Wait", "AUT Lead Nurture With Wait", "auto",
             "Lead nurture cadence: first-touch Task, wait 3 days, warm up if still untouched, second Task, wait 7 days, then cool down "
             "unconverted leads and e-mail the creator.")
    f.var("inLeadId", "String", inp=True)
    f.var("outStage", "String", out=True)
    f.var("varStep", "Number", scale=0, default=0)
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxTomorrow", "Date", "TODAY() + 1")
    f.tt("ttBody", "Lead {!Get_Lead.FirstName} {!Get_Lead.LastName} ({!Get_Lead.Company}) did not convert after the 10-day nurture cadence.")
    f.get("Get_Lead", "Lead", [("Id", "EqualTo", R("inLeadId"))], "Dec_Lead_Open", "Log_Fault", first=True)
    f.decision("Dec_Lead_Open", [("Open", [("Get_Lead", "IsNull", False), ("Get_Lead.IsConverted", "EqualTo", False)], "Create_First_Touch")],
               "Asg_Skipped", "Converted or Missing")
    f.create("Create_First_Touch", "Task", {"Subject": PFX + "Nurture: first touch", "WhoId": R("inLeadId"), "OwnerId": R("Get_Lead.CreatedById"),
                                            "ActivityDate": R("fxTomorrow"), "Priority": "Normal", "Status": "Not Started"}, "Asg_Step_1", "Log_Fault")
    f.assign("Asg_Step_1", [("varStep", "Assign", 1)], "Wait_3_Days")
    f.wait("Wait_3_Days", "Three_Days_Passed", R("fxNow"), 3, "Days", "Get_Lead_After_First", "Log_Fault")
    f.get("Get_Lead_After_First", "Lead", [("Id", "EqualTo", R("inLeadId"))], "Dec_Still_New", "Log_Fault", first=True)
    f.decision("Dec_Still_New", [
        ("Converted", [("Get_Lead_After_First.IsConverted", "EqualTo", True)], "Asg_Converted"),
        ("Untouched", [("Get_Lead_After_First.Status", "EqualTo", "Open - Not Contacted")], "Update_Lead_Warm")],
        "Wait_7_Days", "In Progress")
    f.update("Update_Lead_Warm", "Lead", [("Id", "EqualTo", R("inLeadId"))], {"Rating": "Warm"}, "Create_Second_Touch", "Log_Fault")
    f.create("Create_Second_Touch", "Task", {"Subject": PFX + "Nurture: second touch", "WhoId": R("inLeadId"), "OwnerId": R("Get_Lead.CreatedById"),
                                             "ActivityDate": R("fxTomorrow"), "Priority": "High", "Status": "Not Started"}, "Wait_7_Days", "Log_Fault")
    f.wait("Wait_7_Days", "Seven_Days_Passed", R("fxNow"), 7, "Days", "Get_Lead_Final", "Log_Fault")
    f.get("Get_Lead_Final", "Lead", [("Id", "EqualTo", R("inLeadId"))], "Dec_Converted_Final", "Log_Fault", first=True)
    f.decision("Dec_Converted_Final", [("Converted_Final", [("Get_Lead_Final.IsConverted", "EqualTo", True)], "Asg_Converted")], "Update_Lead_Cold", "Not Converted")
    f.update("Update_Lead_Cold", "Lead", [("Id", "EqualTo", R("inLeadId"))], {"Rating": "Cold"}, "Send_Nurture_Email", "Log_Fault")
    f.email("Send_Nurture_Email", R("$User.Email"), PFX + "Lead nurture finished without conversion", R("ttBody"), "Asg_Cold", "Log_Fault")
    f.assign("Asg_Cold", [("outStage", "Assign", "COLD")])
    f.assign("Asg_Converted", [("outStage", "Assign", "CONVERTED")])
    f.assign("Asg_Skipped", [("outStage", "Assign", "SKIPPED")])
    log_fault(f, record=R("inLeadId"))
    f.start("Get_Lead")
    return f


def contract_renewal():
    f = Flow("AUT_Contract_Renewal_With_Wait", "AUT Contract Renewal With Wait", "auto",
             "Waits until 30 days before a Contract's end date, opens a renewal Opportunity (if none), waits 14 days and escalates "
             "with a Task and e-mail when the renewal is still open.")
    f.var("inContractId", "String", inp=True)
    f.var("outResult", "String", out=True)
    f.var("varRenewalOppId", "String")
    f.formula("fxRenewalAlarm", "DateTime", "DATETIMEVALUE({!Get_Contract.EndDate}) - 30")
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxRenewalName", "String", f"LEFT('{PFX}Renewal - ' & {{!Get_Contract.ContractNumber}}, 120)")
    f.formula("fxCloseDate", "Date", "{!Get_Contract.EndDate}")
    f.tt("ttEscalation", "Renewal for contract {!Get_Contract.ContractNumber} is still open 16 days before the contract end date ({!Get_Contract.EndDate}).")
    f.get("Get_Contract", "Contract", [("Id", "EqualTo", R("inContractId"))], "Dec_Contract_Valid", "Log_Fault", first=True)
    f.decision("Dec_Contract_Valid", [("Valid", [("Get_Contract", "IsNull", False), ("Get_Contract.EndDate", "IsNull", False)], "Wait_Until_Renewal_Window")],
               "Asg_Skipped", "Invalid")
    f.wait("Wait_Until_Renewal_Window", "Renewal_Window_Open", R("fxRenewalAlarm"), 0, "Hours", "Get_Contract_Current", "Log_Fault")
    f.get("Get_Contract_Current", "Contract", [("Id", "EqualTo", R("inContractId"))], "Dec_Still_Active", "Log_Fault", first=True)
    f.decision("Dec_Still_Active", [("Active", [("Get_Contract_Current.Status", "EqualTo", "Activated")], "Get_Existing_Renewal")], "Asg_Skipped", "Not Active")
    f.get("Get_Existing_Renewal", "Opportunity", [("AccountId", "EqualTo", R("Get_Contract.AccountId")), ("Name", "EqualTo", R("fxRenewalName"))],
          "Dec_Renewal_Exists", "Log_Fault", first=True)
    f.decision("Dec_Renewal_Exists", [("Exists", [("Get_Existing_Renewal", "IsNull", False)], "Asg_Existing_Renewal")], "Create_Renewal_Opportunity", "Create")
    f.assign("Asg_Existing_Renewal", [("varRenewalOppId", "Assign", R("Get_Existing_Renewal.Id"))], "Wait_14_Days")
    f.create("Create_Renewal_Opportunity", "Opportunity", {"Name": R("fxRenewalName"), "AccountId": R("Get_Contract.AccountId"), "StageName": "Prospecting",
                                                           "CloseDate": R("fxCloseDate"), "OwnerId": R("Get_Contract.OwnerId"), "Type": "Existing Customer - Upgrade"},
             "Wait_14_Days", "Log_Fault", id_to="varRenewalOppId")
    f.wait("Wait_14_Days", "Fourteen_Days_Passed", R("fxNow"), 14, "Days", "Get_Renewal_Status", "Log_Fault")
    f.get("Get_Renewal_Status", "Opportunity", [("Id", "EqualTo", R("varRenewalOppId"))], "Dec_Renewal_Closed", "Log_Fault", first=True)
    f.decision("Dec_Renewal_Closed", [("Closed", [("Get_Renewal_Status.IsClosed", "EqualTo", True)], "Asg_Renewed")], "Create_Escalation_Task", "Still Open")
    f.create("Create_Escalation_Task", "Task", {"Subject": PFX + "Renewal at risk", "WhatId": R("varRenewalOppId"), "OwnerId": R("Get_Contract.OwnerId"),
                                                "Description": R("ttEscalation"), "Priority": "High", "Status": "Not Started"}, "Send_Escalation_Email", "Log_Fault")
    f.email("Send_Escalation_Email", R("$User.Email"), PFX + "Renewal at risk", R("ttEscalation"), None, "Log_Fault")
    f.assign("Asg_Renewed", [("outResult", "Assign", "RENEWAL_CLOSED")])
    f.assign("Asg_Skipped", [("outResult", "Assign", "SKIPPED")])
    log_fault(f, record=R("inContractId"))
    f.start("Get_Contract")
    return f


ALL = [pipeline_summary, task_reassign, contact_snapshot, lead_nurture, contract_renewal]
