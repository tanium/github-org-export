import requests
import os
import json
import re
import time
import sys

try:
    GH_API_KEY = os.environ['GITHUB_TOKEN']
    ORG_NAME = os.environ['GITHUB_ORG_NAME'] 
except:
    print "\nSet env vars 'GITHUB_TOKEN', 'GITHUB_ORG_NAME' and run again\n"
    quit()
REPOS_PER_EXPORT = 100
LOCK_REPOSITORIES = 'false'
HEADERS = {}
USER_AGENT = { "User-Agent": "curl/7.47.0"}
HEADER_ACCEPT = { "Accept": "application/vnd.github.wyandotte-preview+json" }
GH_AUTH_HEADER = { "Authorization": "token %s" % GH_API_KEY }
OUT_FILE = 'repos.json'
GH_URL = 'https://api.github.com'
ORGS_MIGRATION_ENDPOINT = '/orgs/%s/migrations' % ORG_NAME
REPOS_ENDPOINT = '/orgs/%s/repos' % ORG_NAME
ORG_USER_ENDPOINT = '/orgs/%s/members' % ORG_NAME
CACHE_DIR = 'repo_out/'
UCACHE_DIR = 'user_out/'
R_NAME_FILE = 'repo_names.txt'
U_NAME_FILE = 'user_names.txt'
REPOS_TARGET = GH_URL + REPOS_ENDPOINT
USERS_TARGET = GH_URL + ORG_USER_ENDPOINT
HEADERS.update(HEADER_ACCEPT)
HEADERS.update(GH_AUTH_HEADER)
HEADERS.update(USER_AGENT)
MIG_OUT_DIR = './mig_out'


def get_pages(r):
    """
    Extracts page count from headers.
    """
    r_link = r.headers["Link"]
    m = re.split('=', r_link)
    m = m[3]
    m = re.search('[0-9].', m)
    pages = int(m.group(0))
    return pages

def get_repo_info():
    """
    Makes initial request to get headers, writes each paged json listing of repositories
    to CACHE_DIR.
    """
    r = requests.get(url=REPOS_TARGET, headers=HEADERS)
    pages = get_pages(r)

    for i in range(1, pages + 1):
        next_target = REPOS_TARGET + '?page=%s' % i
        r = requests.get(url=next_target, headers=HEADERS)
        j_text = json.loads(r.text)
        with open('%s%s.json' % (CACHE_DIR, i), 'w') as f:
            f.write(json.dumps(j_text, indent=4, sort_keys=True))

def repo_names():
    """
    Reads previously created paged json listing of repos, extracts repository names,
    writes a new single file containing all repositories as ORG/reponame.
    """
    j_files = os.listdir(CACHE_DIR)
    repo_names = open(R_NAME_FILE, 'w+')
    for file in j_files:
        with open('%s%s' % (CACHE_DIR, file), 'r') as f:
            j_data = json.loads(f.read())
        for key in j_data:
            if 'name' in key:
                repo = '%s/%s' % (ORG_NAME, key['name'])
                repo_names.write("%s\n" % repo)
    repo_names.close()
    print 'Repo names in %s' % R_NAME_FILE

def get_user_pages():
    """
    Writes out json formatted responses for paginated user listing for org. 
    """
    r = requests.get(url=USERS_TARGET, headers=HEADERS)
    pages = get_pages(r)

    for i in range(1, pages +1):
        next_target = USERS_TARGET + '?page=%s' % i
        r = requests.get(url=next_target, headers=HEADERS)
        j_user = json.loads(r.text)
        with open('%s%s.json' % (UCACHE_DIR, i), 'w') as f:
            f.write(json.dumps(j_user, indent=4, sort_keys=True))

def do_users():
    """
    Pulls all users associated with the org. Not strictly needed for migration, but
    a good bit of information to have post import on appliance in case you need
    to check what a user previously had access to.
    """
    u_files = os.listdir(UCACHE_DIR)
    user_names = open(U_NAME_FILE, 'w+')
    for file in u_files:
        with open('%s%s' % (UCACHE_DIR, file), 'r') as f:
            u_data = json.loads(f.read())
        for key in u_data:
            log_in = '%s\n' % key['login']
            u_url = '%s\n' % key['html_url']
            user_names.write(log_in)
            user_names.write(u_url)
    user_names.close()
    print "users in %s" % U_NAME_FILE

def create_migration_bundles():
    """
    Builds a string from the repos pulled containing REPOS_PER_EXPORT number of
    repositories. This turned out to be partly useless. We write out the json for each
    paged response, which also contains the size of the repository. There's a limit on
    the size of each export bundle, and 3.7G is really close to that maximum. Requesting
    too many at once when size is not considered will return an error AFTER the migration
    endpoint tries to build the bundle. For this to be useful, your total combined
    repository size should be under 4G, which may mean massaging the repo_names file
    with the help of professional services.
    """
    repo_list = []

    with open(R_NAME_FILE, 'r') as f:
        repo_list = f.read().splitlines()

    # replace read repo_list for a shorter feedback loop while testing.
    #repo_list = ['ORG/santa_tracker', 'ORG/packer-openstack']
    x = 0
    y = REPOS_PER_EXPORT
    while x < len(repo_list):
        batch_list = []
        if len(repo_list) >= y:
            for i in range(x, y):
                item = repo_list[0]
                batch_list.append(item)
                repo_list.remove(item)
            print batch_list
            migration_url = GH_URL + ORGS_MIGRATION_ENDPOINT
            s_list = convert_list_str(batch_list, y)
            migration_data = '{"lock_repositories":%s,"repositories":%s}' % (LOCK_REPOSITORIES, s_list)
            print "\nRequesting export for %s repositories" % len(s_list)
            r = requests.post(url=migration_url, headers=HEADERS, data=migration_data)
            j_mig = json.loads(r.text)
            mig_jig(j_mig, s_list)
        else:
            migration_url = GH_URL + ORGS_MIGRATION_ENDPOINT
            s_list = convert_list_str(repo_list, y)
            migration_data = '{"lock_repositories":%s,"repositories":%s}' % (LOCK_REPOSITORIES, s_list)
            print "\nRequesting export for %s repositories" % len(s_list)
            r = requests.post(url=migration_url, headers=HEADERS, data=migration_data)
            j_mig = json.loads(r.text)
            mig_jig(j_mig, s_list)
            break
    
def convert_list_str(repolist, max):
    """
    Post data is json format, but we stashed the repos by writing out lists. Convert
    single quotes to double quotes. Easy peasy.
    """
    return str(repolist).replace("'", '"', max+max+max)

def mig_jig(j_mig, repos):
    '''Details hashed out in-line. sorry.'''
    try:
        #write out url and guild from first json response. You CANNOT unlock repos later without
        #the url returned during the migration request. Save them. guids returned by 
        #migration endpoint turned out to be not useful.
        url = j_mig['url']
        guid = j_mig['guid']
    except:
        #if url and guid are not keys in json response, we did something wrong.
        print "\nAPI didn't like that. This might be because you requested too many repos at once.\nHere's the output:"
        print j_mig
        quit()
    #Per export, we create directories and files
    this_mig_dir = (MIG_OUT_DIR + '/' + guid)
    this_url_file = '%s/url' % this_mig_dir
    this_guid_file = '%s/guid' % this_mig_dir
    this_repo_file = '%s/repos' % this_mig_dir

    if not os.path.exists(this_mig_dir):
        os.mkdir(this_mig_dir)
    with open(this_url_file, 'w') as f:
        f.write(url)
    with open(this_guid_file, 'w') as f:
        f.write(guid)
        f.write('\n')
    with open(this_repo_file, 'w') as f:
        f.write(repos)
    #spin on export status, download archive when ready.
    archive_url = wait_export_ready(url, guid)
    download_archive(archive_url, this_mig_dir)
    
def wait_export_ready(url, guid):
    e_status = 'exporting'
    check_count = 1
    while e_status != 'exported':
        r = requests.get(url=url, headers=HEADERS)
        j_check = json.loads(r.text)
        try:
            e_status = j_check['state']
            if e_status == 'exporting':
                sys.stdout.write( "\r\nExporting %s : %s (retries)"  % (guid, check_count) )
                sys.stdout.flush()
                nemui()
            if e_status == 'pending':
                sys.stdout.write( "\r\n%s is pending : %s (retries)" % (guid, check_count) )
                sys.stdout.flush()
                nemui()
            if e_status == 'failed':
                #stop, drop, and roll
                #This is a realy bad place to be. You now have stacks of exports
                #but no idea where you left off. A good TODO would be to save off the
                #remaining repos and load that list when restarting the script as priority.
                #Getting here means starting over.
                print '''\ndudebro, migration endpoint says export failed.
                        the failure was on %s
                        ''' % guid
                exit()
            if e_status == 'exported':
                print ''
                archive_url = j_check['archive_url']
                return archive_url
        except:
            print "\nCould not find 'state' key in server response"
            print "\nserver response:"
            print json.dumps(j_check, indent=4, sort_keys=True)
            #Do what status == failed does here too. 
            exit()
        check_count += 1
    

def download_archive(url, guiddir):
    r = None
    dl_archive = None
    archive_url = url
    filepath = '%s/migration_archive.tar.gz' % guiddir
    with open(filepath, 'wb') as dl_archive:
        print '\nDownloading %s for %s' % (archive_url, guiddir)
        r = requests.get(archive_url, headers=HEADERS, stream=True, allow_redirects=True)
        total_length = r.headers.get('content-length')
        if total_length is None: 
            # no content length header, can't do progress bar thing
            dl_archive.write(r.content)
        else:
            dl = 0
            total_length = int(total_length)
            # Downloads slowed way, way down our last few exports (#s 16-19). Chunk size weirdness
            # was an attempt to resolve that.
            for data in r.iter_content(chunk_size=5*1024*1024):
                dl += len(data)
                dl_archive.write(data)
                done = int(50 * dl / total_length)
                sys.stdout.write( "\r[%s%s]  %s of %s bytes" % ('=' * done, ' ' * (50-done), dl, int(total_length) ) )
                sys.stdout.flush()
    

def nemui():
    time.sleep(30)

if __name__ == '__main__':
    if not os.path.exists(MIG_OUT_DIR):
        os.mkdir(MIG_OUT_DIR)
    if not os.path.exists(CACHE_DIR):
        os.mkdir(CACHE_DIR)
    if len(os.listdir(CACHE_DIR)) == 0:
        get_repo_info()
        repo_names()
    if not os.path.exists(UCACHE_DIR):
        os.mkdir(UCACHE_DIR)
    if len(os.listdir(UCACHE_DIR)) == 0:
        get_user_pages()
    do_users()
    #create_migration_bundles()
    print''
    