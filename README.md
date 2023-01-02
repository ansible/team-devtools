# devtools

This repository is used to share practices, workflows and decisions affecting projects maintained by Ansible DevTools team.

## Main devtools project dependencies

```mermaid
graph LR;

  classDef tsclass fill:#f90,stroke:#f90,color:#333;
  classDef containerclass fill:#060,stroke:#060,color:#fff;
  classDef thirdpartyclass fill:#9f6,stroke:#9f6,color:#333;
  classDef collectionclass fill:#c00,stroke:#c00,color:#fff;
  classDef pyclass fill:#09f,stroke:#09f,color:#fff;
  classDef ghaclass fill:#ee0,stroke:#ee0,color:#000;


  ansible-lint-action --> creator-ee;
  creator-ee --> ansible-lint;

  ansible-lint --> ansible-compat;
  ansible-compat -.-> community.molecule;
  molecule --> ansible-compat;
  molecule -.-> community.molecule:::collectionclass;
  creator-ee:::containerclass --> molecule;
  vscode-ansible:::tsclass --> ansible-language-server;
vscode-ansible:::tsclass --> vscode-yaml;
  ansible-language-server -.-> creator-ee;

  molecule-podman --> molecule;
  ansible-navigator -.-> ansible-lint;
  ansible-navigator -.-> creator-ee;

 ansible-lint:::pyclass;
 ansible-compat:::pyclass;
 molecule:::pyclass;
 molecule-podman:::pyclass;
 ansible-navigator:::pyclass;
 ansible-language-server:::tsclass;
 vscode-yaml:::tsclass;
 ansible-lint-action:::ghaclass;
 click ansible-lint-action href "https://github.com/ansible-community/ansible-lint-action"
 click community.molecule "https://github.com/ansible-collections/community.molecule"
 click molecule href "https://github.com/ansible-community/molecule"
 click molecule-podman href "https://github.com/ansible-community/molecule-podman"
 click creator-ee href "https://github.com/ansible/creator-ee"
 click ansible-lint href "https://github.com/ansible/ansible-lint"
 click ansible-compat href "https://github.com/ansible/ansible-compat"
 click ansible-navigator href "https://github.com/ansible/ansible-navigator"
 click ansible-language-server href "https://github.com/ansible/ansible-language-server"
 click vscode-ansible href "https://github.com/ansible/vscode-ansible"
 click vscode-yaml href "https://github.com/redhat-developer/vscode-yaml"
```

Note:
1. [vscode-yaml](https://github.com/redhat-developer/vscode-yaml) project is not directly supported by Ansible devtools team.
2. dotted lines are either test, build or optional requirements
3. 📘 python, 📙 typescript, 📕 ansible collection, 📗 container 📒 github action

## Molecule ecosystem

```mermaid
graph LR;

  molecule-podman --> molecule;
  molecule-docker --> molecule;
  molecule-containers -.-> molecule-podman;
  molecule-containers -.-> molecule-docker;
  molecule-vagrant --> molecule;

  molecule-libvirt --> molecule;
  molecule-lxd --> molecule;


  pytest-molecule --> molecule;
  tox-ansible -.-> molecule;
  tox-ansible -.-> ansible-test;


 click molecule href "https://github.com/ansible-community/molecule"
 click molecule-podman href "https://github.com/ansible-community/molecule-podman"
```
