from os import listdir, walk
from os.path import isdir, isfile, basename, join, relpath
import re

CacheDir('build_cache')

AddOption('--nbd', type='string', metavar='DEVICE',
          help='nbd device to use for mounting images')

if not GetOption('nbd'):
    print "-" * 35 + "> Missing required parameter: --nbd"
    Return()

AddOption('--flatten', action="store_true", default=False,
          help='flatten the final layer into image.qcow2')


def download_base_image():
    base_name = 'CentOS-6-x86_64-GenericCloud-1510.qcow2'
    image = 'build/%s' % base_name
    md5sum = 'fe5c8d4469e6925d6cbb20b830b9d1ac'

    dl_env = Environment()
    dl_env.Decider(lambda dependency, target, prev_ni: target.get_csig() != md5sum)
    dl_env.Command(image, '/bin/true', """
cd build && \
curl --silent -O http://cloud.centos.org/centos/6/images/{0}.xz && \
xz -d {0}.xz
""".format(base_name))
    NoCache(image)
    return image


def create_targets(env):
    """Creates the series of output targets"""
    next_base = download_base_image()

    for dir in get_layer_dirs():
        image = 'build/%s.qcow2' % dir
        build_layer = join(dir, 'build-layer')
        modify_disk = join(dir, 'modify-disk')
        if isfile(build_layer):
            nodes = env.Layer(image, [next_base] + Recurse(dir))
            script = build_layer
        elif isfile(modify_disk):
            nodes = env.DiskMod(image, [next_base] + Recurse(dir))
            script = modify_disk
        else:
            continue

        with open(script, 'r') as f:
            for line in f:
                if line.startswith('# nocache'):
                    NoCache(image)
                    break
                elif line.startswith('# noshare'):
                    nodes[0].noshare = True

        next_base = image

    if GetOption('flatten'):
        nodes = env.MergeLayers('build/image.qcow2', [next_base])
        # hack! monkey-patch scons so it doesn't waste time creating checksums for this huge file
        import types, binascii, os
        rand_hash = lambda x: binascii.b2a_hex(os.urandom(16))
        nodes[0].get_content_hash = types.MethodType(rand_hash, nodes[0])
    else:
        env.LinkLayers('build/image.qcow2', [next_base])

    NoCache('build/image.qcow2')


def generate_env():
    env = Environment()
    env['NBD_DEVICE'] = GetOption('nbd')
    env['ROOT_REL_SRC'] = lambda target, source, env, for_signature: \
        relpath(str(Dir('#')), str(source[1]))
    env['ROOT_REL_TARGET'] = lambda target, source, env, for_signature: \
        relpath(str(Dir('#')), str(target[0].dir))
    env['SRC_REL_TARGET'] = lambda target, source, env, for_signature: \
        relpath(str(source[0]), str(target[0].dir))

    # Command to build a layer.  Take care to use relative paths, so that the
    # qemu snapshot chain will work if the images are moved around.  Also, because
    # the command string is part of scons' cache signature.
    build_layer="""
cd ${TARGET.dir} \
&& qemu-img create -f qcow2 -b ${SRC_REL_TARGET} -o compat=0.10 ${TARGET.file} \
&& cd ${ROOT_REL_TARGET}/${SOURCES[1]} \
&& sudo ${ROOT_REL_SRC}/bin/qemu-chroot \
    --image ${ROOT_REL_SRC}/${TARGET} --device $( ${NBD_DEVICE} $) --mount-entrypoint ./build-layer
    """

    env['BUILDERS']['Layer'] = Builder(action=build_layer)

    # Command to make a layer by modifying the raw disk, rather
    # than mounting a chroot.  This allows a layer to resize the source.
    diskmod="""
cd ${TARGET.dir} \
&& sudo ${ROOT_REL_TARGET}/${SOURCES[1]}/modify-disk \
    ${SRC_REL_TARGET} ${TARGET.file} $( ${NBD_DEVICE} $)
    """

    env['BUILDERS']['DiskMod'] = Builder(action=diskmod)

    # Command to merge layers into an output image.
    merge_layers="""
cd ${TARGET.dir} \
&& qemu-img create -f qcow2 -b ${SRC_REL_TARGET} -o compat=0.10 ${TARGET.file} \
&& qemu-img rebase -p -b '' ${TARGET.file}
    """

    env['BUILDERS']['MergeLayers'] = Builder(action=merge_layers)

    # Command to symlink a layer to another
    link_layers="ln -sf ${SOURCE.file} ${TARGET}"
    env['BUILDERS']['LinkLayers'] = Builder(action=link_layers)

    return env


def get_layer_dirs():
    """Returns a list of directories containing layer definitions"""
    root = Dir('#').path
    layer_dirs = [dir for dir in listdir(root) if isdir(dir)
                  and re.match('^[0-9]{2,}_', basename(dir))]
    return sorted(layer_dirs)


def Recurse(dir):
    """Walks dir to create a list of scons Dir and File nodes"""
    matches = []
    for root, dirnames, filenames in walk(dir):
        matches.append(Dir(root))
        matches.extend([Dir(join(root, d)) for d in dirnames])
        matches.extend([File(join(root, f)) for f in filenames])
    return matches


env = generate_env()
create_targets(env)
