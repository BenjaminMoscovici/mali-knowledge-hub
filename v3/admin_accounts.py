"""Server-only administrator records. Public profile metadata never grants access."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
import ipaddress


class AdminStore:
    def __init__(self, db, bootstrap):
        self.db, self.bootstrap = db, sorted(bootstrap)

    def call(self, name, **params):
        return self.db.rpc('mkh_admin_' + name, params).execute().data

    def is_admin(self, uid):
        return self.call('allowed', p_user=uid, p_bootstrap=self.bootstrap) is True

    def pending(self, email):
        rows = (self.db.table('mkh_admin_invitations')
                .select('id,email,expires_at').eq('email', email.casefold())
                .eq('status', 'pending').gt('expires_at', datetime.now(timezone.utc).isoformat())
                .order('created_at', desc=True).limit(1).execute().data or [])
        return rows[0] if rows else None

    def create(self, uid, email):
        return self.call('invite', p_actor=uid, p_email=email, p_bootstrap=self.bootstrap)

    def delivered(self, invite_id, ok):
        self.call('delivery', p_invitation=invite_id, p_ok=ok)

    def check(self, uid, invite_id):
        return self.call('check_invite', p_user=uid, p_invitation=invite_id, p_bootstrap=self.bootstrap)

    def accept(self, uid, invite_id):
        return self.call('accept', p_user=uid, p_invitation=invite_id, p_bootstrap=self.bootstrap)

    def revoke(self, uid, invite_id):
        return self.call('revoke', p_actor=uid, p_invitation=invite_id, p_bootstrap=self.bootstrap)

    def overview(self):
        def rows(table, columns, limit=100):
            return self.db.table(table).select(columns).order('created_at', desc=True).limit(limit).execute().data or []
        jobs = (self.db.table('ingestion_jobs')
                .select('id,filename,status,error,uploaded_at,uploaded_by,metadata,quality,document_id')
                .order('uploaded_at', desc=True).limit(100).execute().data or [])
        return {'invitations': rows('mkh_admin_invitations','id,email,status,created_at,expires_at,accepted_at'),
                'administrators': rows('mkh_admin_members','user_id,email,created_at'),
                'source_requests': rows('mkh_admin_source_requests','id,title,url,organization,notes,status,created_at'),
                'audit': rows('mkh_admin_audit','id,actor_id,action,target_id,created_at',50), 'jobs':jobs}

    def source_request(self, uid, data):
        return self.call('source_request', p_actor=uid, p_data=data, p_bootstrap=self.bootstrap)

    def audit(self, uid, action, target):
        self.call('record', p_actor=uid, p_action=action, p_target=target, p_bootstrap=self.bootstrap)


def source_request(data):
    """Register an endpoint for review; never fetch it or accept embedded secrets."""
    result = {}
    for key, maximum in [('title',160),('url',1000),('organization',160),('notes',1000)]:
        value = data.get(key, '')
        if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 and c not in '\n\t' for c in value):
            raise ValueError('Enter a valid source title, public HTTPS URL and description.')
        result[key] = value.strip()
    parsed = urlsplit(result['url'])
    if not result['title'] or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use a public HTTPS source URL without passwords, tokens, query parameters or fragments.')
    host = parsed.hostname.casefold()
    if host=='localhost' or host.endswith(('.localhost','.local','.internal')) or '.' not in host:
        raise ValueError('Use a public source address.')
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError('Use a public source address.')
    except ValueError as exc:
        if str(exc)=='Use a public source address.': raise
    return result
