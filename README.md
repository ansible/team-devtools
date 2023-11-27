# devtools

This repository is used to share practices, workflows and decisions affecting projects maintained by Ansible DevTools team.

## Python DevTools project dependencies

It should be noted that our vscode extension would either depend on `ansible-dev-tools` python package or directly use the `creator-ee` container (execution environment).

```mermaid
graph LR;

  classDef tsclass fill:#f90,stroke:#f90,color:#333;
  classDef containerclass fill:#060,stroke:#060,color:#fff;
  classDef thirdpartyclass fill:#9f6,stroke:#9f6,color:#333;
  classDef collectionclass fill:#c00,stroke:#c00,color:#fff;
  classDef pyclass fill:#09f,stroke:#09f,color:#fff;


subgraph supported
  ansible-lint
  ansible-navigator
end

subgraph tech-preview
  ansible-development-environment
  ansible-creator
  pytest-ansible
  tox-ansible
  molecule
end

  creator-ee:::containerclass --> ansible-dev-tools;

  ansible-dev-tools --> ansible-lint;
  ansible-dev-tools --> ansible-navigator;
  ansible-dev-tools --> molecule;

  ansible-lint --> ansible-compat;
  ansible-compat -.-> community.molecule;
  molecule --> ansible-compat;
  molecule -.-> community.molecule:::collectionclass;

  ansible-navigator -.-> ansible-lint;
  ansible-navigator -.-> creator-ee;


  ansible-dev-tools --> ansible-development-environment;
  ansible-dev-tools --> ansible-creator;
  ansible-dev-tools --> pytest-ansible;
  ansible-dev-tools --> tox-ansible;

  ansible-compat:::pyclass;
  ansible-creator:::pyclass;
  ansible-dev-tools:::pyclass;
  ansible-development-environment:::pyclass;
  ansible-lint:::pyclass;
  ansible-navigator:::pyclass;
  molecule:::pyclass;
  tox-ansible:::pyclass;
  pytest-ansible:::pyclass;

  click ansible-development-environment "https://github.com/ansible/ansible-development-environment"
  click community.molecule "https://github.com/ansible-collections/community.molecule"
  click molecule href "https://github.com/ansible/molecule"
  click creator-ee href "https://github.com/ansible/creator-ee"
  click ansible-lint href "https://github.com/ansible/ansible-lint"
  click ansible-compat href "https://github.com/ansible/ansible-compat"
  click ansible-navigator href "https://github.com/ansible/ansible-navigator"
  click ansible-creator href "https://github.com/ansible/ansible-creator"
  click tox-ansible href "https://github.com/ansible/tox-ansible"
  click pytest-ansible href "https://github.com/ansible/pytest-ansible"
```

Note:

1. [vscode-yaml](https://github.com/redhat-developer/vscode-yaml) project is not directly supported by Ansible devtools team.
2. dotted lines are either test, build or optional requirements
3. 📘 python, 📕 ansible collection, 📗 container
4. `community.molecule` is only a test dependency of molecule core.

## TypeScript Dependencies (extension)

```mermaid
graph LR;

  classDef tsclass fill:#f90,stroke:#f90,color:#333;
  classDef containerclass fill:#060,stroke:#060,color:#fff;
  classDef thirdpartyclass fill:#9f6,stroke:#9f6,color:#333;

  vscode-ansible:::tsclass --> ansible-language-server;
  vscode-ansible:::tsclass --> vscode-yaml;
  vscode-yaml:::tsclass;
  ansible-language-server:::tsclass;

 click ansible-development-environment "https://github.com/ansible/ansible-development-environment"
 click community.molecule "https://github.com/ansible-collections/community.molecule"
 click creator-ee href "https://github.com/ansible/creator-ee"
 click ansible-language-server href "https://github.com/ansible/ansible-language-server"
 click vscode-ansible href "https://github.com/ansible/vscode-ansible"
 click vscode-yaml href "https://github.com/redhat-developer/vscode-yaml"
```

## Collections included in creator-ee

`creator-ee` execution environment is a development container that contains
most of the most important tools used in the development and testing of collections. Still,
while we bundle several collections in it, you need to be warned that **we might
remove any included collection without notice** if that prevents us from
building the container.

```mermaid
graph LR;

creator-ee --> ansible.posix;
creator-ee --> ansible.windows;
creator-ee --> awx.awx;
creator-ee --> containers.podman;
creator-ee --> kubernetes.core;
creator-ee --> redhatinsights.insights;
creator-ee --> theforeman.foreman;
```

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
