"""Small helper that queries a locally running OpenTripPlanner 2.10 server (GTFS GraphQL API) for itineraries."""
import json
import urllib.request

FEED = 'J1925'   # feedId set in build-config.json by make_otp_inputs.py

PLAN_Q = """
query($o:String!, $d:String!, $t:OffsetDateTime!, $w:Duration, $n:Int) {
  planConnection(
    origin: {location: {stopLocation: {stopLocationId: $o}}}
    destination: {location: {stopLocation: {stopLocationId: $d}}}
    dateTime: {earliestDeparture: $t}
    searchWindow: $w
    first: $n
    modes: {transitOnly: true}
  ) {
    searchDateTime
    routingErrors { code description inputField }
    pageInfo { searchWindowUsed hasNextPage endCursor }
    edges { node {
      start end duration numberOfTransfers waitingTime walkTime
      systemNotices { tag text }
      legs {
        mode transitLeg serviceDate
        start { scheduledTime } end { scheduledTime }
        from { name stop { gtfsId parentStation { gtfsId } } }
        to { name stop { gtfsId parentStation { gtfsId } } }
        route { gtfsId shortName }
        trip { gtfsId tripShortName }
      }
    } }
  }
}
"""


def gql(port, query, variables=None, timeout=600):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/otp/gtfs/v1',   # run_otp_check.sh binds the servers to 127.0.0.1
                                 data=json.dumps({'query': query, 'variables': variables or {}}).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def plan(port, o, d, t_iso, window='PT6H', n=100):
    """o and d are parent stations of the published dataset (PS...). t_iso looks like '1925-04-05T08:00+09:00'."""
    r = gql(port, PLAN_Q, {'o': f'{FEED}:{o}', 'd': f'{FEED}:{d}', 't': t_iso, 'w': window, 'n': n})
    if 'errors' in r:
        raise RuntimeError(r['errors'])
    return r['data']['planConnection']
