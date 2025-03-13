# Home Assistant Besen BS20 integration 

It's a quick and dirty integration for the BESEN BS20 wall EV charger.
If you have any suggestions (for example unmapped vaules, or others) please
feel free to post an [issue](https://github.com/sustainabledeveloper/bs20/issues).

Now you can Start/Stop charging, and chang the max current value (during charging as well).
You need to switch on the Unlock switch to send these commands to the wallbox. If you want to prevent to send, turn it off. 

[![BuyMeCoffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/schy)

## Device support
BESEN BS20

FTE Maximal Wallbox

Morec Wallbox

Astoneves 22kW Wallbox EV


## Installation

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

Installation is easiest via the [Home Assistant Community Store
(HACS)](https://hacs.xyz/), which is the best place to get third-party
integrations for Home Assistant. Once you have HACS set up, simply click the button below (requires My Homeassistant configured) or
follow the [instructions for adding a custom
repository](https://hacs.xyz/docs/faq/custom_repositories) and then
the integration will be available to install like any other.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sustainabledeveloper&repository=bs20&category=integration)

## Configuration

### Prerequisites
- You need to establish the connection between the charger and EVSEMaster app by bluetooth.
- You need to set the WIFI configuration in EVSEMaster app.
- Make sure (after a restart of the app) EVSEMaster connects to the charger by WIFI.
- Your Home Assistant installation have to be on the same network as the charger.
- UDP port 28376 not be used by any other integration.

IP address is automatically determined, so you don't need to know it.

You need the serial number of the device, which can be found in the EVSEMaster app.

And also you need the password, you already set in the EVSEMaster. If you not, the default password will be 123456.

After adding the integration to Home Assistant, the enties should be appear with UNKNOWN values. After a few seconds they should be changed the values that the charger sent to the network.

In a docker setup you need to configure the following (Thanks for the instruction to @b2un0):

```yaml
ports:
- "28376:28376/udp"
```

## Troubleshoot

If you have successfully add the integration and the device to Home Assistant, but no data received, you need to check the following:
- With WireShark check if a device send periodically (about every 10 seconds) a datagram on UDP to 255.255.255.255 from port 30139 to port 28376. If not, check if the charger connects to the same network.

If data received when EVSEMaster app is running, but if not, datas are not changing:
- Change check if you typed the correct Serial number and password on the integration setup.
