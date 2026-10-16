"""Validate the current isolated Docker API route before any fixture request."""
from ipaddress import IPv4Address, IPv4Interface, IPv4Network, ip_network
import re

from blank_server_smoke import require

PRIVATE = tuple(IPv4Network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def unpublished(container):
    # Internal bridges suppress the template's requested loopback bindings.
    # Assert actual mappings here; the global production port guard is separate.
    ports = container['NetworkSettings']['Ports']
    require(ports is None or type(ports) is dict and all(
        bindings is None or type(bindings) is list and not bindings for bindings in ports.values()),
        'published fixture binding refused')


def internal_origin(container, network, project):
    try:
        require(all(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value)
                    for value in (container['Id'], network['Id'])), 'invalid Docker identity')
        labels = container['Config']['Labels']
        require(labels['com.docker.compose.service'] == 'api' and labels['com.docker.compose.project'] == project,
                'foreign API container')
        require(container['State']['Running'] is True and container['State'].get('Restarting') is False,
                'API is not running')
        name = project + '_default'
        attachments = container['NetworkSettings']['Networks']
        require(set(attachments) == {name} and network['Name'] == name and network['Driver'] == 'bridge'
                and network['Internal'] is True, 'foreign fixture network')
        require(network['Labels']['com.docker.compose.project'] == project
                and network['Labels']['com.docker.compose.network'] == 'default', 'foreign network owner')
        attachment = attachments[name]
        require(attachment['NetworkID'] == network['Id'], 'stale network identity')
        address = IPv4Address(attachment['IPAddress'])
        require(any(address in block for block in PRIVATE), 'nonprivate API address')
        subnets = [ip_network(item['Subnet']) for item in network['IPAM']['Config']]
        subnet = next(block for block in subnets if isinstance(block, IPv4Network) and address in block
                      and any(block.subnet_of(private) for private in PRIVATE))
        require(address not in (subnet.network_address, subnet.broadcast_address), 'invalid API host address')
        endpoint = IPv4Interface(network['Containers'][container['Id']]['IPv4Address'])
        require(endpoint.ip == address and endpoint.network == subnet
                and attachment['IPPrefixLen'] == subnet.prefixlen, 'stale API endpoint')
        unpublished(container)
        return f'http://{address}:8080'
    except Exception:
        raise ValueError('invalid internal fixture route') from None
