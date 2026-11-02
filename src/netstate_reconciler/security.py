from __future__ import annotations
import ipaddress, re
from dataclasses import dataclass
from typing import Any
from .mcp_client import result_text

@dataclass
class ProbeAssessment:
    status: str
    reachable: bool | None
    summary: str
    evidence: str
    policy_evidence: dict[str, Any] | None = None

def _counter(line: str) -> int | None:
    m = re.search(r"\((\d+)\s+match(?:es|\(es\))?\)", line, re.I)
    return int(m.group(1)) if m else None

def _network(address: str, wildcard: str | None):
    try:
        if address.lower() == 'any': return ipaddress.ip_network('0.0.0.0/0')
        if not wildcard: return ipaddress.ip_network(address + '/32', strict=False)
        mask = (~int(ipaddress.IPv4Address(wildcard))) & 0xffffffff
        return ipaddress.IPv4Network(f'{address}/{ipaddress.IPv4Address(mask)}', strict=False)
    except Exception: return None

def _rules(text: str) -> list[dict[str, Any]]:
    rules=[]; acl=''
    for line in text.splitlines():
        h=re.search(r'(?:Extended|Standard) IP access list\s+(\S+)', line, re.I)
        if h: acl=h.group(1); continue
        # IOS extended ACL entry, with optional wildcard masks and a displayed match counter.
        m=re.search(r'\b(deny|permit)\s+(ip|icmp|tcp|udp)\s+(any|\d+(?:\.\d+){3})(?:\s+(\d+(?:\.\d+){3}))?\s+(any|\d+(?:\.\d+){3})(?:\s+(\d+(?:\.\d+){3}))?', line, re.I)
        count=_counter(line)
        if m and acl and count is not None:
            action,proto,src,sw,dst,dw=m.groups()
            rules.append({'acl':acl,'action':action.lower(),'proto':proto.lower(),'src':src,'sw':sw,'dst':dst,'dw':dw,'count':count,'line':line.strip()})
    return rules

def confirm_policy_block(before: dict[str,str], after: dict[str,str], source_ip: str | None, destination_ip: str) -> dict[str,Any] | None:
    """Confirm only when matching deny counter increases and same ACL is inbound-attached."""
    if not source_ip: return None
    try: src_ip=ipaddress.ip_address(source_ip); dst_ip=ipaddress.ip_address(destination_ip)
    except ValueError: return None
    for device, aft in after.items():
        bef=before.get(device,''); old_rules=_rules(bef); new_rules=_rules(aft)
        for rule in new_rules:
            if rule['action'] != 'deny': continue
            sn=_network(rule['src'],rule['sw']); dn=_network(rule['dst'],rule['dw'])
            if not sn or not dn or src_ip not in sn or dst_ip not in dn: continue
            prior=next((r['count'] for r in old_rules if r['acl']==rule['acl'] and r['line'].split('(')[0].strip()==rule['line'].split('(')[0].strip()),None)
            if prior is None or rule['count'] <= prior: continue
            if re.search(r'inbound\s+access list is\s+'+re.escape(rule['acl'])+r'\b',aft,re.I):
                return {'confirmed':True,'device':device,'acl':rule['acl'],'rule':rule['line'],'counter_before':prior,'counter_after':rule['count'],'source_ip':source_ip,'destination_ip':destination_ip,'attachment':'inbound','reason':'Matching deny-rule counter increased during the probe and the ACL is reported as inbound-applied.'}
    return None

def assess_reachability(result: Any, policy_evidence: dict[str,Any] | None = None) -> ProbeAssessment:
    text=result_text(result); low=text.lower()
    if policy_evidence and policy_evidence.get('confirmed') is True:
        return ProbeAssessment('BLOCKED_BY_POLICY',False,'A matching ACL deny counter increased during this probe, and the ACL is confirmed as inbound-applied.',text,policy_evidence)
    # Packet count format returned by the Packet Tracer MCP tool.
    m=re.search(r'sent\s*=\s*(\d+).*?received\s*=\s*(\d+)',low,re.S)
    if m:
        sent,received=map(int,m.groups())
        if sent>0 and received==sent: return ProbeAssessment('REACHABLE',True,f'All {received}/{sent} probe packets received replies.',text)
        if received>0: return ProbeAssessment('PARTIAL_CONNECTIVITY',None,f'Partial connectivity: {received}/{sent} probe packets received replies. Packet loss alone does not prove a policy block.',text)
        if sent>0: return ProbeAssessment('NO_CONNECTIVITY',False,'No probe packets received replies. Cause is unconfirmed; this is not proof of an ACL block.',text)
    if '"reachable": true' in low or '"success": true' in low: return ProbeAssessment('REACHABLE',True,'The source device received successful ICMP replies.',text)
    if any(x in low for x in ('"reachable": false','"success": false','0% success','0 percent success','success rate is 0','100% packet loss','100 percent packet loss','destination host unreachable','request timed out','request timeout','timed out')):
        return ProbeAssessment('NO_CONNECTIVITY',False,'No ICMP reply was observed. Cause is unconfirmed; packet loss alone does not prove an ACL block.',text)
    if any(x in low for x in ('100% success','100 percent success','success rate is 100','5/5','4/4')): return ProbeAssessment('REACHABLE',True,'The source device received successful ICMP replies.',text)
    return ProbeAssessment('INCONCLUSIVE',None,'The response did not contain enough reliable evidence to classify the result.',text)

def security_findings(result: Any) -> list[dict[str,str]]:
    text=result_text(result); findings=[]
    for line in text.splitlines():
        s=line.strip(); low=s.lower()
        if any(t in low for t in ('missing','weak','disabled','telnet','no local user','type 7')): findings.append({'severity':'REVIEW','evidence':s})
    return findings
