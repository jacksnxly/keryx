# Security Checklist

OWASP Top 10 adapted for code review. Check each category relevant to the implementation.

## A01: Broken Access Control

Check for:
- [ ] Missing authentication on endpoints
- [ ] Missing authorization checks
- [ ] Direct object references without ownership validation
- [ ] Path traversal vulnerabilities (`../` in file paths)
- [ ] CORS misconfiguration

Search patterns:
```
# Missing auth middleware
grep -r "app.get\|app.post" --include="*.ts" | grep -v "auth"

# Direct ID usage without validation
grep -r "req.params.id" --include="*.ts"
```

## A02: Cryptographic Failures

Check for:
- [ ] Hardcoded secrets/API keys
- [ ] Weak encryption algorithms
- [ ] Sensitive data in logs
- [ ] Passwords in plaintext
- [ ] Missing HTTPS enforcement

Search patterns:
```
# Hardcoded secrets
grep -rE "(password|secret|api_key|apikey|token)\s*=\s*['\"]" --include="*.ts"

# Sensitive data logging
grep -r "console.log.*password\|console.log.*token" --include="*.ts"
```

## A03: Injection

Check for:
- [ ] SQL injection (string concatenation in queries)
- [ ] NoSQL injection
- [ ] Command injection (shell execution with user input)
- [ ] LDAP injection
- [ ] XSS (unescaped user input in HTML)

Search patterns:
```
# SQL injection
grep -rE "query\(.*\+.*\)|execute\(.*\+.*\)" --include="*.ts"

# Command injection
grep -r "exec\|spawn\|execSync" --include="*.ts"

# XSS
grep -r "innerHTML\|dangerouslySetInnerHTML" --include="*.tsx"
```

## A04: Insecure Design

Check for:
- [ ] Missing rate limiting
- [ ] No input validation
- [ ] Unbounded resource allocation
- [ ] Missing business logic validation

## A05: Security Misconfiguration

Check for:
- [ ] Debug mode enabled in production
- [ ] Default credentials
- [ ] Unnecessary features enabled
- [ ] Missing security headers
- [ ] Verbose error messages exposing internals

Search patterns:
```
# Debug mode
grep -r "DEBUG=true\|NODE_ENV.*development" --include="*.ts"

# Verbose errors
grep -r "stack\|stackTrace" --include="*.ts"
```

## A06: Vulnerable Components

Check for:
- [ ] Known vulnerable dependencies
- [ ] Outdated packages
- [ ] Unnecessary dependencies

```bash
# Check for known vulnerabilities
npm audit
```

## A07: Authentication Failures

Check for:
- [ ] Weak password requirements
- [ ] Missing brute force protection
- [ ] Session fixation
- [ ] Insecure session storage
- [ ] Missing MFA where required

## A08: Data Integrity Failures

Check for:
- [ ] Missing input validation
- [ ] Deserialization of untrusted data
- [ ] Missing integrity checks on critical data

## A09: Logging & Monitoring Failures

Check for:
- [ ] Missing audit logs for security events
- [ ] Sensitive data in logs
- [ ] No alerting for suspicious activity

## A10: Server-Side Request Forgery (SSRF)

Check for:
- [ ] User-controlled URLs in server requests
- [ ] Missing URL validation
- [ ] Internal network access from user input

Search patterns:
```
# User-controlled URLs
grep -r "fetch\|axios\|request" --include="*.ts" | grep -v "node_modules"
```

## Scoring Security Issues

| Severity | Confidence Score |
|----------|-----------------|
| Critical (RCE, auth bypass) | 100 |
| High (injection, data exposure) | 90 |
| Medium (XSS, CSRF) | 80 |
| Low (information disclosure) | 70 |
| Info (best practice) | 50 |

Only report security issues ≥80 confidence as blocking.
