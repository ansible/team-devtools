# Ansible filesystem requirements

For security reasons Ansible will refuse to load any configuration files from **world-writable filesystems** (`o+w`). You can find more details on [#42388](https://github.com/ansible/ansible/issues/42388)

## WSL on Windows

Both WSL1 and WSL2 default mounting of Windows drive on Linux uses insecure file permissions, so you will not be able to run Ansible correctly from paths like `/mnt/c`. Still, if Ansible is installed on linux partition, it will work.

You can also try to reconfigure `/etc/wsl.conf` to ensure that your Windows mounts do have UNIX compatible permissions that are not insecure. For example our team is using a configuration like below for testing:

```ini
# /etc/wsl.conf
[automount]
enabled = true
root = /
options = "metadata,umask=077"
[interop]
enabled = false
appendWindowsPath = false
[network]
hostname = wsl
```

To test that your changes are working correctly, just to a `ls -la /mnt/c` and check if `o+w` is still present or not. You can even try to remove the write permissions for others from a file in order to see if chmod works on that particular drive: `chmod o-w filename`.

### Performance

Filesystem operations from Windows mount under WSL are **very slow** on both versions of WSL so we strongly recommend you to avoid using them.

On some versions of Windows there were even bugs causing system instability and kernel panic when a lot of activity happened on these. We hope that these were addressed but you need to aware of them.
