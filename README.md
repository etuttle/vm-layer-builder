A fast, incremental image builder based on qemu-img, scons, and chroot.  Kinda like `docker build`,
except it creates VM images.

## How does it work?

Images are composed of layers.  Each layer is written to a qcow2 snapshot which is "backed" by the
previous layer.  The final image is produced by flattening the snapshot chain into a single file.
Each layer is cached for reuse based on the checksum of input files.

You can create branches of the source and switch around between them.  Because the cache is
checksum-based, layers will only be built if their inputs haven't been built before.

## Why a layer based image builder?

Say you'll be maintaining a VM image, which you expect to update periodically.  Consider your
options for managing the image:

* Automate a build from on the base OS (eg, packer or kickstart):  On the plus side, changes are
tracked in source code.  But every change requires a full build, which can be slow.  Even
worse, the build isn't repeatable -- OS packages change over time, so any build might
pull in a new package that breaks something.  Yes, this does happen in practice!  

* Modify your image manually, and release snapshots:  A convenient approach, and changes are
predictable, but the build steps aren't recorded.  It's difficult to rebuild a pristine image, or
produce a changelog, or manage different branches, or figure out what change broke something...

* vm-layer-builder:  Convenient, repeatable, with changes tracked in code.  For each change, you have
a choice between a quick incremental (add a new layer) or a full rebuild (modify the base layer).
Incremental changes can be periodically "rolled up" into a base layer.

## Usage
 
The script looks for folders with names matching \d\d_name, with a `build-layer` or `modify-disk`
script inside.  New layer folders can be created with `./bin/new-layer <layer-name>`.

During a build, the script for each layer is called in a chroot, with its folder mounted at /mnt.

To build an image:

`scons --cache-debug=- --nbd=/dev/nbd0`  (use an available nbd device)

Cache-debug is recommended to see the cache signatures that scons has generated for each layer.

Output will be at `build/image.qcow2`.

By default, the image is not flattened into a single file because this process can take a few
minutes.  Rather `build/image.qcow2` is a symlink to the last layer, which allows
commands like test-boot to work.  To build and flatten the layers into `image.qcow2`, add
`--flatten` to the arguments.

Do a test boot with qemu (does not modify the image - filesystem changes are discarded): 

`./bin/test-boot`

Type `^a x` to exit out of the qemu environment. 

## Cache Options

Layers are cached by default.  However if a layer and its children are deterministic and quick to
build, there's no reason to cache it -- it's cache only serves to clutter up the cache dir.
You can disable the cache for such layers by adding a `# nocache` hint to the script file.

When using the s3_cache plugin, a `# noshare` hint will use the local scons cache but disable
cache sharing for a layer.  This might be appropriate for layers that are deterministic
but large.  Without `noshare`, they will cause an unnecessary and slow upload every time they are built. 

It is pointless to cache layers that are decendants of uncached layers, since the cached output
will only be reused if two builds produce byte-identical versions of the uncached
parent layers.  Thus images should be organized with non-deterministic layers first (which should
be cached), followed by noshare layers, followed by nocache layers.

## Requirements

* `nbd` kernel module
* `qemu-img` (developed on 1.5.3 from CentOS 7 using the Enterprise Virtualization version)
* `scons` (developed on 2.3.0 from Centos 7)
* `cloud-utils`, specifically the `growpart` command
* password-less sudo access

The `test-boot` script additionally requires a VT-x capable host and qemu-kvm, with
bridge networking configured.

## Setting up a CentOS 7 vm-development-vm

VMWare is recommended because unlike Virtualbox, it supports VT-x in guests.

Install a CentOS vm from the minimal ISO.  Enable VT-X in the CPU settings:

![image](doc/vtx.png)

... and create an admin account for yourself.  Use `sudo gpasswd -a $USER wheel` and `visudo` to
setup NOPASSWD sudo access.

Install mainline kernel, enable the nbd driver, and reboot:

```
sudo rpm -Uvh http://www.elrepo.org/elrepo-release-7.0-2.el7.elrepo.noarch.rpm
sudo yum -y --enablerepo=elrepo-kernel install kernel-ml

sudo grep menuentry.*elrepo.x86_64 /boot/grub2/grub.cfg
sudo vi /etc/sysconfig/grub
# update like GRUB_DEFAULT="CentOS Linux (4.3.3-1.el7.elrepo.x86_64) 7 (Core)"
sudo grub2-mkconfig -o /boot/grub2/grub.cfg

echo '#!/bin/sh
if [ ! -c /dev/nbd0 ] ; then
        exec /sbin/modprobe nbd max_part=63 >/dev/null 2>&1
fi
' | sudo tee /etc/sysconfig/modules/nbd.modules
sudo chmod +x /etc/sysconfig/modules/nbd.modules

sudo reboot
```

Install other requirements:

```
sudo yum install -y centos-release-qemu-ev
sudo yum install -y qemu-img-ev scons cloud-utils
```

Optional: setup mDNS so you can ssh to the VM using `ssh vm-builder.local`:

```
sudo hostnamectl set-hostname vm-builder
sudo yum install -y avahi
sudo yum remove firewalld
sudo systemctl start avahi-daemon
sudo systemctl enable avahi-daemon
# fix slow DNS on ssh connection
echo "UseDNS no" | sudo tee -a /etc/ssh/sshd_config
sudo systemctl restart sshd
```

Optional: install vmware tools so shared folder mounts work (in /mnt/hgfs):

```
sudo yum --enablerepo=elrepo-kernel install kernel-ml-devel kernel-ml-headers
sudo yum install -y epel-release net-tools
sudo yum install -y dkms perl
sudo mkdir /mnt/cdrom
# choose Install VMWare Tools first in the UI
sudo mount /dev/sr0 /mnt/cdrom/
cd
tar zxvf /mnt/cdrom/VMwareTools-*.tar.gz 
cd vmware-tools-distrib/
sudo ./vmware-install.pl -f -d
```

Install qemu and setup bridge access (required for test-boot script)

```
sudo yum install -y qemu qemu-kvm-ev bridge-utils
interface=$(cd /sys/class/net/ && ls -d en* | head -1)
sudo cp /etc/sysconfig/network-scripts/{ifcfg-$interface,ifcfg-br0}
sudo sed -i -e /UUID/d -e s/$interface/br0/ -e s/Ethernet/Bridge/ /etc/sysconfig/network-scripts/ifcfg-br0 
echo DELAY=0 | sudo tee -a /etc/sysconfig/network-scripts/ifcfg-br0
sudo sed -i -e /DEFROUTE/d -e /PEER/d -e /IPV4/d -e /IPV6/d -e 's/BOOTPROTO.*/BOOTPROTO=none/' /etc/sysconfig/network-scripts/ifcfg-$interface
echo BRIDGE=br0 | sudo tee -a /etc/sysconfig/network-scripts/ifcfg-$interface
sudo gpasswd -a $USER kvm
echo "allow br0" | sudo tee -a /etc/qemu-kvm/bridge.conf
# also disable predictable interface names, or the image may break on other VMWare installs:
sudo mv /etc/sysconfig/network-scripts/{ifcfg-$interface,ifcfg-eth0}
sudo sed -i -e "s/$interface/eth0/g" /etc/sysconfig/network-scripts/ifcfg-eth0
sudo vi /etc/default/grub 
# add net.ifnames=0 to GRUB_CMDLINE_LINUX
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
sudo yum erase -y biosdevname
sudo reboot
```

## Generating a cloud-localds image

cloud-localds test-boot/cloud-init.img test-boot/user-data.yaml test-boot/meta-data.yaml

virsh attach-device sfo2-dev-vmdev019.sfo2.zoosk.com cloud-disk.xml --config
