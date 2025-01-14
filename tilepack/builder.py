import argparse
import csv
import gzip
import mercantile
import multiprocessing
import os,sys
import random
import requests
import signal
import tilepack.outputter
import time
import traceback

shutdown_event = multiprocessing.Event()
verbose = False

class ShutdownException(Exception):
    pass

sess = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=200)
sess.mount('https://', adapter)

# def fetch_tile(x, y, z, type, layer, tile_size, tile_format, api_key):
def fetch_tile(format_args):
    sleep_time = 0.5 * random.uniform(1.0, 1.7)
    response_info = []

    if shutdown_event.is_set():
        raise ShutdownException("Shutdown event set")

    while True:
        # url = '{url_prefix}/{type}/v1/{size}/{layer}/{zoom}/{x}/{y}.{fmt}'.format(**format_args)
        url = '{url_prefix}/{zoom}/{x}/{y}.{fmt}'.format(**format_args)

        api_key = format_args.get('api_key')
        if api_key:
            url += '?api_key={api_key}'.format(**format_args)

        try:
            start = time.time()

            resp = sess.get(url, timeout=(6.1, 30))

            data = resp.content
            finish = time.time()

            response_info.append({
                "url": url,
                "response status": resp.status_code,
                "server": resp.headers.get('Server'),
                "time to headers millis": int(resp.elapsed.total_seconds() * 1000),
                "time for content millis": int((finish - start) * 1000),
                "response length bytes": len(data),
            })

            resp.raise_for_status()
            return (format_args, response_info, data)
        # except requests.exceptions.RequestException as e:
        #     if isinstance(e, requests.exceptions.HTTPError):
        #         if e.response.status_code == 404:
        #             if verbose:
        #                 print("HTTP {} -- {} while retrieving {}. Not trying again.".format(
        #                     e.response.status_code, e.response.text.strip(), url)
        #                 )
        #             return (format_args, response_info, None)
        #         else:
        #             print("HTTP {} -- {} while retrieving {}, retrying after {:0.2f} sec".format(
        #                 e.response.status_code, e.response.text.strip(), url, sleep_time)
        #             )
        #     else:
        #         print("{} while retrieving {}, retrying after {:0.2f} sec".format(
        #             type(e), url, sleep_time)
        #         )
        #     time.sleep(sleep_time)
        #     sleep_time = min(sleep_time * 2.0, 30.0) * random.uniform(1.0, 1.7)
        # except Exception as e:
        #     print("Ran into an unexpected exception: {}".format(e))
        #     traceback.print_tb()
        #     raise
        except :
            print("trying url {0} but {1} occured".format(url,sys.exc_info()[0]))
            break 

output_type_mapping = {
    'mbtiles': tilepack.outputter.MbtilesOutput,
    'zipfile': tilepack.outputter.ZipfileOutput,
    'null': tilepack.outputter.NullOutput,
}

def build_tile_packages(min_lon, min_lat, max_lon, max_lat, min_zoom, max_zoom,
        type, layer, tile_size, tile_format, tile_compression, output, output_formats,
        api_key, url_prefix, concurrency):

    fetches = []
    for x, y, z in mercantile.tiles(min_lon, min_lat, max_lon, max_lat, range(min_zoom, max_zoom + 1)):
        fetches.append(dict(
            url_prefix=url_prefix,
            x=x,
            y=y,
            zoom=z,
            type=type,
            layer=layer,
            size=tile_size,
            fmt=tile_format,
            api_key=api_key,
        ))

    tiles_to_get = len(fetches)
    tiles_written = 0
    tiles_errored = 0
    response_info_writer = csv.DictWriter(
        open('{}.responses.csv'.format(output), 'w'),
        ["url", "response status", "server", "time to headers millis", "time for content millis", "response length bytes"],
    )
    response_info_writer.writeheader()

    tile_ouputters = []
    for t in set(output_formats):
        builder_class = output_type_mapping.get(t)

        if not builder_class:
            raise KeyError("Unknown output format {}".format(t))

        tile_ouputters.append(builder_class.build_from_basename(output))

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    p = multiprocessing.Pool(concurrency)

    def sigint_handler(signal_num, frame):
        shutdown_event.set()
        print("Shutdown event set")
    signal.signal(signal.SIGINT, sigint_handler)

    for t in tile_ouputters:
        t.open()
        t.add_metadata('name', output)
        # FIXME: Need to include the `json` key
        t.add_metadata('format', 'application/vnd.mapbox-vector-tile')
        if tile_compression:
            t.add_metadata('compression', 'deflate')
        t.add_metadata('bounds', ','.join(map(str, [min_lon, min_lat, max_lon, max_lat])))
        t.add_metadata('minzoom', min_zoom)
        t.add_metadata('maxzoom', max_zoom)

    try:
        for format_args, response_info, data in p.imap_unordered(fetch_tile, fetches):
            if data:
                tiles_written += 1
                for t in tile_ouputters:
                    if tile_compression:
                        t.add_tile(format_args, gzip.compress(data))
                    else:
                        t.add_tile(format_args, data)
            else:
                tiles_errored += 1

            response_info_writer.writerows(response_info)

            if (tiles_written + tiles_errored) % 500 == 0:
                print("{} good, {} errored of {} ({:0.2f}%) tiles for {}".format(
                    tiles_written,
                    tiles_errored,
                    tiles_to_get,
                    ((tiles_written + tiles_errored) / float(tiles_to_get)) * 100.0,
                    output
                ))
    except :
        # print("Workers shut down")
        print("{0} occured".format(sys.exc_info()[0]))

    p.close()
    p.join()
    for t in tile_ouputters:
        t.close()

    print("{} good, {} errored of {} ({:0.2f}%) tiles for {}".format(
        tiles_written,
        tiles_errored,
        tiles_to_get,
        ((tiles_written + tiles_errored) / float(tiles_to_get)) * 100.0,
        output
    ))

    output_data = {
        'number_tiles': tiles_to_get,
        'tiles_written': tiles_written,
        'tiles_errored': tiles_errored,
    }

    if shutdown_event.is_set():
        output_data['shutdown_requested'] = True

    return output_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('min_lon',
        type=float,
        help='Bounding box minimum longitude/left')
    parser.add_argument('min_lat',
        type=float,
        help='Bounding box minimum latitude/bottom')
    parser.add_argument('max_lon',
        type=float,
        help='Bounding box maximum longitude/right')
    parser.add_argument('max_lat',
        type=float,
        help='Bounding box maximum latitude/top')
    parser.add_argument('min_zoom',
        type=int,
        help='The minimum zoom level to include')
    parser.add_argument('max_zoom',
        type=int,
        help='The maximum zoom level to include')
    parser.add_argument('output',
        help='The filename for the output tile package')
    parser.add_argument('--layer',
        default='all',
        help='Layer')
    parser.add_argument('--type',
        default='vector',
        choices=['vector', 'terrain'],
        help='Type')
    parser.add_argument('--tile-size',
        default='512',
        choices=['256', '512'],
        help='The size of tile')
    parser.add_argument('--tile-format',
        default='mvt',
        help='The Mapzen Vector Tile format to request')
    parser.add_argument('--tile-compression',
        default=False,
        action='store_true',
        help='Compress individual tiles')
    parser.add_argument('--output-formats',
        default='mbtiles,zipfile',
        help='A comma-separated list of output formats to write to (mbtiles, zipfile, or null)')
    parser.add_argument('-j', '--concurrency',
        type=int,
        default=multiprocessing.cpu_count() * 8,
        help='The size of the process pool to use when downloading tiles')
    args = parser.parse_args()

    api_key = os.environ.get('MAPZEN_API_KEY')
    url_prefix = os.environ.get('MAPZEN_URL_PREFIX') or "http://localhost:8000/all"

    output_formats = args.output_formats.split(',')
    build_tile_packages(
        args.min_lon,
        args.min_lat,
        args.max_lon,
        args.max_lat,
        args.min_zoom,
        args.max_zoom,
        args.type,
        args.layer,
        args.tile_size,
        args.tile_format,
        args.tile_compression,
        args.output,
        output_formats,
        api_key,
        url_prefix,
        args.concurrency,
    )

if __name__ == '__main__':
    main()
