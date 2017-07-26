from urllib3.exceptions import ReadTimeoutError
from elasticsearch.exceptions import ConnectionTimeout
from time import sleep
import re
import logging

id_xplodr = re.compile(r'^(?P<site>\w{2})-(?P<numeric>\d+)$')


class PortalItemNotFound(StandardError):
    pass


def do_search(esclient, cfg, query, wait_time=2, retries=20):
    """
    Performs a seach in ES with exponential backoff for read timeout or connection timeout errors
    :param esclient: elastic search client object
    :param cfg: asset sweeper configuration object
    :param query: elastic search query object as per Elastic Search DSL specification
    :param wait_time: inital time to wait if a timeout occurs, in seconds.  this is doubled every time a successive error occurs
    :return: elastic search result dictionary
    """
    attempt=0
    while True:
        attempt+=1
        try:
            result = esclient.search(index=cfg.value('portal_elastic_index'),doc_type='item',body=query)
            return result
        except ReadTimeoutError as e:
            logging.warning(str(e))
            if attempt>retries:
                raise
            sleep(wait_time)
            wait_time *= 2
        except ConnectionTimeout as e:
            logging.warning(str(e))
            if attempt>retries:
                raise
            sleep(wait_time)
            wait_time *= 2


def lookup_portal_item(esclient, cfg, item_id):
    """
    Returns an array of the collections that this item belongs to, according to Portal's ES index.
    Raises PortalItemNotFound if there is no result for that item ID
    Can raise underlying network/Elasticsearch exceptions as well if something breaks further down.
    :param esclient: Elastic search client
    :param cfg: Asset Sweeper configuration object
    :param item_id: Item ID to look up
    :return: List of collection IDs, or None if no collection IDs were found (but the item did exist)
    """
    parts = id_xplodr.match(item_id)
    if parts is None:
        raise ValueError("{0} is not a valid Vidispine ID".format(item_id))

    query = {
        'query': {
            'filtered': {
                'filter': {
                    'term': {
                        'vidispine_id_str_ex': item_id
                    }
                }
            }
        }
    }

    result = do_search(esclient, cfg, query)

    hits = result['hits']['hits']
    if len(hits)==0: raise PortalItemNotFound(item_id)

    #pprint(hits[0]['_source'])
    if not 'f___collection_str' in hits[0]['_source']:
        return None

    #use this to determine if it is online or nearline
    #on_storages = hits[0]['_source']['storage_original']
    #storage_count = hits[0]['_source']['storage_original_size']
    return hits[0]['_source']['f___collection_str'] #this is an array


def process_row(esclient, cfg, row, totals):
    """
    Process a row from the database
    :param esclient: Elastic search client
    :param cfg: configuration object
    :param row: List or tuple of (item_id, size_in_bytes)
    :param totals: Dictionary of totals to update
    :return: New dictionary of totals
    """
    if row[0] is None:
        totals['unimported'] += float(row[1])/(1024.0**2)
        return totals #the item has not yet been imported
    logging.debug("Got {0} with size {1}".format(row[0],row[1]))
    try:
        collections = lookup_portal_item(esclient,cfg,row[0])
    except PortalItemNotFound:
        logging.warning("Portal item {0} was not found in the index".format(row[0]))
        collections = None
    except ValueError:
        logging.error("Got an invalid vidispine ID '{0}' from the database. Corruption?".format(row[0]))
        return totals
    if collections is None:
        totals['unattached'] += float(row[1])/(1024.0**2)
        return totals
    for c in collections:
        if not c in totals:
            totals[c] = float(row[1])/(1024.0**2)
        else:
            totals[c] += float(row[1])/(1024.0**2)
    return totals