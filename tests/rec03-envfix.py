# REC-03 drill helper: beta's scan posture. `vidra setup --scan=false` still writes CLAMAV_ADDR
# + MALWARE_SCAN_MODE=fail-closed (finding F2 of the v0.6.3->v0.6.4 record), and deploy.sh's
# preflight refuses that combination.
import os, re
p = "/opt/vidra/env/production.env"
s = open(p).read()
s = re.sub(r"(?m)^MALWARE_SCAN_MODE=.*$", "MALWARE_SCAN_MODE=disabled", s)
s = re.sub(r"(?m)^CLAMAV_ADDR=.*$", "# CLAMAV_ADDR unset for the REC-03 drill: unscanned on purpose (beta posture)", s)
if "MALWARE_SCAN_MODE=" not in s:
    s += "MALWARE_SCAN_MODE=disabled\n"
tmp = p + ".tmp"
open(tmp, "w").write(s); os.chmod(tmp, 0o600); os.replace(tmp, p)
print("scan posture applied")
