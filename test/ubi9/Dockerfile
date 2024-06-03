FROM registry.access.redhat.com/ubi9/ubi:latest as adt

COPY <<EOF /etc/yum.repos.d/aap.repo
[aap25]
name=aap25
baseurl='https://rhsm-pulp.corp.stage.redhat.com/content/beta/layered/rhel$releasever/$basearch/ansible-developer/1-beta/os/'
gpgcheck=0
enabled=1
module_hotfixes=1
EOF

RUN <<EOF
    dnf remove -y subscription-manager dnf-plugin-subscription-manager
    dnf install -y ansible-dev-tools
    dnf clean all
EOF
RUN <<EOF
    set -e
    echo "Show adt version."
    adt --version
    echo "Show ansible-creator version."
    ansible-creator --version
    echo "Show ansible-lint version."
    ansible-lint --version
    echo "Show ansible-navigator version."
    ansible-navigator --version
    echo "Show molecule version."
    molecule --version
    echo "Show ade version."
    ade --version
    echo "Check if tox recognizes tox-ansible plugin."
    tox --version | grep tox-ansible
    echo "Check if pytest recognizes pytest-ansible plugin."
    pytest-3.11 --version -VV | grep pytest-ansible
EOF
