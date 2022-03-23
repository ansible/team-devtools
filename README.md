# devtools
[POC] Shared practices, workflows and decisions impacting Ansible devtools projects

## Main devtools project dependencies

```mermaid
  graph LR;
      ansible-lint-action --> creator-ee;
      creator-ee --> ansible-lint;

      ansible-lint --> ansible-compat;
      molecule --> ansible-compat;
      creator-ee --> molecule;
      vscode-ansible --> ansible-language-server;
      ansible-language-server --> ansible-lint;
      ansible-language-server --> creator-ee;

      molecule-podman --> molecule;
      ansible-language-server --> schemas;
      ansible-lint --> schemas;
      ansible-navigator --> ansible-lint;
```
