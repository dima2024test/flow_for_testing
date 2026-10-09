from flowlib import Flow, R, D

LOGGER = "AUT_Log_Flow_Error"
PFX = "[Flow Demo] "


def log_fault(f, name="Log_Fault", record=None, severity="Error", nxt=None, owner=None):
    """Fault-path handler: calls the shared logging subflow with $Flow.FaultMessage."""
    inputs = {
        "inFlowName": f.api,
        "inErrorMessage": R("$Flow.FaultMessage"),
        "inSeverity": severity,
    }
    if record is not None:
        inputs["inRecordId"] = record
    if owner is not None:
        inputs["inOwnerId"] = owner
    return f.subflow(name, LOGGER, inputs, nxt=nxt)


def admin_lookup(f, nxt, fault, prof="Get_Admin_Profile", user="Get_Admin_User"):
    """Two-step lookup of an active System Administrator user (used as record owner in automated contexts)."""
    f.get(prof, "Profile", [("Name", "EqualTo", "System Administrator")], nxt=user, fault=fault, first=True)
    f.get(user, "User", [("ProfileId", "EqualTo", R(f"{prof}.Id")), ("IsActive", "EqualTo", True)],
          nxt=nxt, fault=fault, first=True, sort="CreatedDate", order="Asc")
