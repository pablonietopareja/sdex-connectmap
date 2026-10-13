# Security policy and deployment guidance

SDEX ConnectMap is an administrative topology viewer for controlled networks. I maintain it on a best-effort basis without a contractual response time, certification or security SLA.

## Report a vulnerability

Use **Security > Report a vulnerability** in this repository when private vulnerability reporting is enabled. If that option is unavailable, open a minimal issue requesting a private contact channel. Do not publish exploit details, credentials, internal URLs or customer information in a public issue.

Include the affected version or commit, impact and a synthetic reproduction. Test reports against an isolated environment rather than an operational industrial gateway.

## Access and network boundary

ConnectMap has no built-in authentication, user roles or separate viewer permissions. Any client reaching the service can read topology and change the local profile and presentation settings. Topology responses contain operational addresses and connection names.

The supplied deployment binds its published port to `127.0.0.1`. Remote access requires a deliberate bind-address change and appropriate firewall, VPN or authenticated reverse-proxy controls. Terminate browser HTTPS at the reverse proxy and protect configuration routes as well as the UI, static files and event stream.

The SDEX target may legitimately be on a private industrial network. ConnectMap does not apply a hostname/IP allowlist to configuration requests and does not provide network-level SSRF isolation. Restrict ingress to trusted administrators and egress to the required SDEX origin. Rate limits and browser-origin checks are not substitutes for authentication.

API mutations reject explicit cross-origin browser requests and `Sec-Fetch-Site: cross-site`. CLI requests without those headers remain possible. Reverse proxies must preserve the browser's effective scheme and Host; a mismatch can reject legitimate configuration writes.

## SDEX operations

The runtime performs fixed reads for system information, interface data and supported connection modules. Its SDEX POSTs are limited to login, session refresh and logout. Visual editing writes only ConnectMap's SQLite state. The container does not need privileged mode, host networking, host filesystem access or the Docker socket.

Use a dedicated SDEX account with the least available read permissions. If SDEX rejects an unchanged default password, change it through SDEX administration before connecting; ConnectMap does not perform that operation.

## Credentials and storage

Saved passwords are Fernet-encrypted. Authentication nonces and signatures remain in backend memory and are not returned to the browser. The profile status exposes the configured URL and username, but only indicates whether a password exists.

The generated `/data/.connectmap-key` must persist with the database. An external `CONNECTMAP_SECRET_KEY` replaces that key source; changing it can make saved credentials unreadable. Protect the volume, backups and external secret with filesystem and host access controls. Anyone holding the database and its encryption key can decrypt the password. Other database content is not encrypted.

Avoid bootstrap passwords in shell history or checked-in environment files. Docker environment values are visible to users with Docker administration privileges. Never commit `.env`, database files, keys, diagnostic exports or real SDEX fixtures.

## TLS, errors and bounded requests

SDEX TLS verification is enabled by default. Use a trusted certificate with a matching hostname or IP SAN; private-CA guidance is in [Configuration](docs/CONFIGURATION.md). Disabling verification is an explicit laboratory option with a persistent UI warning and weakens server identity protection.

The HTTP client does not follow redirects or inherit proxy environment variables. Requests have timeouts, limited retries and bounded response sizes. Browser mutations have a body-size limit. Logs and errors use reviewed fields and pattern-based secret redaction; inspect operational reports before sharing them because redaction cannot identify every sensitive industrial label.

SSE queues are bounded per subscriber, but there is no global application-level connection cap or user quota. Use reverse-proxy connection limits where needed. Run a single process per data volume.

## Dependencies and validation

Install the hash-locked Python requirements and npm lockfile, keep base images current and review dependency advisories before distributing an image. Source scans and synthetic tests do not constitute an image OS scan, penetration test or universal SDEX compatibility certification. Consult [Release audit](RELEASE_AUDIT.md) for executed checks and [Deployment](docs/DEPLOYMENT.md) for container acceptance and upgrade precautions.
