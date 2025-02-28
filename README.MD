# Home Assistant Besen BS20 integration 

It's a quick and dirty integrtion for the BESEN BS20 wall EV charger.
If you have any suggestions (for example unmapped vaules, or others) please
feel free to post an [issue](https://github.com/sustainabledeveloper/bs20/issues).

[![BuyMeCoffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/schy)

## Device support


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

You need to know the IP address of the wallbox. If you have no idea, use Wireshark, and scan for the destination address 255.255.255.255. Where the destination port is 28376, that will be
your EV charger.

You need the serial number of the device, which can be found in the EVSEMaster app.

And also you need the password, you already set in the EVSEMaster. If you not, the default password will be 123456.
