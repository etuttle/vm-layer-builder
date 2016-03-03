
# This monkey-patches scons' CacheDir to synchronize the cache
# to an s3 bucket.
#
# To enable it:
#
# - ensure python packages are installed: boto3, humanize
# - create a site_init.py file in site_scons containing 'import s3_cache'
# - setup ~/.aws/credentials with an access key
# - set the SCONS_CACHE_S3_BUCKET environment variable to a bucket name
#
# The --cache-debug=- flag is recommended to see s3 cache operations.

import boto3
import botocore.exceptions
import humanize
import os
import os.path
import stat

import SCons.Action
import SCons.CacheDir
import SCons.Errors

# fail early if SCONS_CACHE_S3_BUCKET is not set
S3_BUCKET = os.environ['SCONS_CACHE_S3_BUCKET']

s3_client = boto3.client('s3')

def make_cache_dir(fs, cachedir):
    if not fs.isdir(cachedir):
        try:
            fs.makedirs(cachedir)
        except EnvironmentError:
            # We may have received an exception because another process
            # has beaten us creating the directory.
            if not fs.isdir(cachedir):
                raise SCons.Errors.EnvironmentError("Unable to create cache dir")


def CacheRetrieveFunc(target, source, env):
    t = target[0]
    fs = t.fs
    cd = env.get_CacheDir()
    cachedir, cachefile = cd.cachepath(t)
    if not fs.exists(cachefile):
        cd.CacheDebug('CacheRetrieve(%s):  %s not in disk cache\n', t, cachefile)
        try:
            # Try to download the file from S3 into the disk cache
            sig = os.path.basename(cachefile)
            head = s3_client.head_object(Bucket=S3_BUCKET, Key=sig)
            download_size = humanize.naturalsize(head['ContentLength'], gnu=True)
            cd.CacheDebug('CacheRetrieve(%%s):  retrieving %%s from s3 (%s)\n' % download_size,
                          t, cachefile)
            make_cache_dir(fs, cachedir)
            # no race here: boto3 downloads to a temp file and then links into place
            s3_client.download_file(S3_BUCKET, sig, cachefile)
        except botocore.exceptions.ClientError as e:
            if int(e.response['Error']['Code']) == 404:
                cd.CacheDebug('CacheRetrieve(%s):  %s not in s3\n', t, cachefile)
                return 1
            else:
                raise SCons.Errors.EnvironmentError('boto exception %s' % e)

    cd.CacheDebug('CacheRetrieve(%s):  retrieving %s from disk cache\n', t, cachefile)
    if SCons.Action.execute_actions:
        if fs.islink(cachefile):
            fs.symlink(fs.readlink(cachefile), t.path)
        else:
            env.copy_from_cache(cachefile, t.path)
        st = fs.stat(cachefile)
        fs.chmod(t.path, stat.S_IMODE(st[stat.ST_MODE]) | stat.S_IWRITE)
    return 0

SCons.CacheDir.CacheRetrieve = SCons.Action.Action(CacheRetrieveFunc, None)

SCons.CacheDir.CacheRetrieveSilent = SCons.Action.Action(CacheRetrieveFunc, None)


def CachePushFunc(target, source, env):
    t = target[0]
    if t.nocache:
        return
    fs = t.fs
    cd = env.get_CacheDir()
    cachedir, cachefile = cd.cachepath(t)
    if fs.exists(cachefile):
        # Don't bother copying it if it's already there.  Note that
        # usually this "shouldn't happen" because if the file already
        # existed in cache, we'd have retrieved the file from there,
        # not built it.  This can happen, though, in a race, if some
        # other person running the same build pushes their copy to
        # the cache after we decide we need to build it but before our
        # build completes.
        cd.CacheDebug('CachePush(%s):  %s already exists in disk cache\n', t, cachefile)
        return

    cd.CacheDebug('CachePush(%s):  pushing %s to disk cache\n', t, cachefile)

    tempfile = cachefile+'.tmp'+str(os.getpid())

    make_cache_dir(fs, cachedir)

    # Unlike the original CachePushFunc, we want any error in the
    # following to halt the build.  This is to ensure that every
    # layer is pushed to the shared cache.
    if fs.islink(t.path):
        fs.symlink(fs.readlink(t.path), tempfile)
    else:
        fs.copy2(t.path, tempfile)
        if t.__dict__.get('noshare', False):
            cd.CacheDebug('CachePush(%s):  not pushing %s to s3 (noshare)\n', t, cachefile)
        else:
            # Upload the file to S3 before linking it into place
            tempfile_size = humanize.naturalsize(fs.getsize(tempfile), gnu=True)
            cache_key = os.path.basename(cachefile)
            cd.CacheDebug('CachePush(%%s):  pushing %%s to s3 (%s)\n' % tempfile_size,
                          t, cachefile)
            try:
                s3_client.upload_file(tempfile, S3_BUCKET, cache_key,
                                      ExtraArgs={'Metadata': {'VM-Layer': str(t)}})
            except botocore.exceptions.ClientError as e:
                # scons doesn't print errors raised here, but it does stop
                print e
                raise SCons.Errors.EnvironmentError('boto exception %s' % e)

    fs.rename(tempfile, cachefile)
    st = fs.stat(t.path)
    fs.chmod(cachefile, stat.S_IMODE(st[stat.ST_MODE]) | stat.S_IWRITE)

SCons.CacheDir.CachePush = SCons.Action.Action(CachePushFunc, None)
