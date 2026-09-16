# Security and CVE handling

## Reporting vulnerabilities

Do not open public GitHub issues for security-sensitive reports.

| Context | Where to report |
|--------|------------------|
| Red Hat Ansible Automation Platform and other Red Hat products | [Red Hat Product Security](https://access.redhat.com/security/report) |
| Ansible open source community projects | [Reporting bugs and security vulnerabilities](https://docs.ansible.com/ansible/latest/community/reporting_bugs_and_security_vulnerabilities.html) |

Include product or repository name, version, component, and steps to reproduce when possible.

## Public CVE identifiers

Common Vulnerabilities and Exposures (CVE) IDs are assigned by CNAs and vendors so customers can track issues across products. A CVE on a container or package does not by itself mean an immediate code change in every repository; remediation depends on where the vulnerable component is built and shipped.

Public references:

- [CVE Program](https://www.cve.org/)
- [Red Hat Security Data](https://access.redhat.com/security/security-updates/)
- [Red Hat Ecosystem Catalog](https://catalog.redhat.com/) (container and product security views on published images)

## How fixes typically reach customers (high level)

For platform and container deliverables, fixes usually flow through vendor builds, errata (RHSA), and refreshed published images. Timelines depend on release trains and support policy for each major version. This repository documents DevTools team practices; it does not define Red Hat product SLAs.

Contributors should not commit ad hoc version bumps in downstream lockfiles to "clear" a CVE without following the product build and compose process for that stream.

## Security trackers

Red Hat tracks many issues as internal security tracking work items linked to CVE and advisory data. Assignment follows component and image ownership. Questions about a specific tracker belong to the assignee and product security process, not public issue comments.

## This repository

`ansible/team-devtools` is documentation and shared practices for the Ansible DevTools team. It is not the primary home for Ansible Automation Platform container build definitions or PSIRT workflow configuration.

For engineering handbook material, see [Ansible engineering handbook](https://handbook.eng.ansible.com/) where published.

## Supported versions

Remediation expectations follow the [Ansible Automation Platform life cycle](https://access.redhat.com/support/policy/updates/ansible-automation-platform) for the version you run. Components outside active support may not receive fixes.
