import os
from pprint import pprint
import logging
import mimetypes
from asset_folder_importer.asset_folder_sweeper.posix_get_mime import posix_get_mime
from asset_folder_importer.asset_folder_sweeper.ignore_list import IgnoreList
from asset_folder_importer.asset_folder_sweeper.assetfolder import get_asset_folder_for
logger = logging.getLogger(__name__)

global_ignore_list = IgnoreList()


def check_mime(fullpath,db):
    statinfo = os.stat(fullpath)
    pprint(statinfo)
    mt = None
    try:
        (mt, encoding) = mimetypes.guess_type(fullpath, strict=False)
    except Exception as e:
        db.insert_sysparam("warning", e.message)

    if mt is None or mt == 'None':
        mt = posix_get_mime(fullpath, db)

    return statinfo, mt


def find_files(cfg,db):
    #Step three. Find all relevant files and bung 'em in the database
    startpath = cfg.value('start_path',noraise=False)

    logger.info("Running from '%s'" % startpath)

    n=0
    for dirpath,dirnames,filenames in os.walk(startpath):
        for name in filenames:
            if name.startswith('.'):
                continue

            shouldIgnore = global_ignore_list.should_ignore(dirpath, name)

            fullpath = os.path.join(dirpath,name)
            logger.debug("Attempting to add file at path: '%s'" % fullpath)
            try:
                asset_folder = get_asset_folder_for(dirpath)
            except ValueError as e:
                logger.error(str(e))
                asset_folder = None
            except IndexError as e:
                logger.warning("Suspicious file path: {0} is too short for an asset folder".format(str(e)))
                asset_folder = None

            try:
                statinfo, mt = check_mime(fullpath,db)
                db.upsert_file_record(dirpath,name,statinfo,mt,asset_folder=asset_folder, ignore=shouldIgnore)

            except UnicodeDecodeError as e:
                db.insert_sysparam("warning",str(e))
                logging.error(str(e))
            except OSError as e:
                db.insert_sysparam("warning",str(e))
                if e.errno == 2: #No Such File Or Directory
                    db.update_file_record_gone(dirpath,name)
            n+=1
            print "%d files...\r" %n

    return n