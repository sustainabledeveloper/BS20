# Besen EV Charger

Home Assistant integration for the BESEN BS20 wall charger and the wallboxes
that share its protocol. Local push over UDP, with an optional Bluetooth
fallback for chargers that lose Wi-Fi.

Reported working with:

* BESEN BS20
* FTE Maximal Wallbox
* Morec Wallbox
* Astoneves 22 kW Wallbox EV
* Telestar EC311

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

[![BuyMeCoffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/schy)

## Breaking changes in 2.x

2.x is a rewrite. Nothing has to be removed or re-added, and the upgrade
migrates the existing entry, but four things change behaviour. Read
[Upgrading from 1.x](#upgrading-from-1x) before updating.

* **`Charging power` now reports the total across all phases.** On a three
  phase charger 1.x showed a third of the real figure. Anything that compares
  this value against a threshold needs its numbers revisited.
* **Entity unique IDs change** from `bs20_<serial>_<camelCase>` to
  `<serial>_<snake_case>`. Entity IDs are preserved, so dashboards,
  automations and history keep working, but a template that builds a unique ID
  by hand does not.
* **Four entities are removed**: `Unknown 1`-`Unknown 4` and
  `Charging current state`. They carried undecoded bytes and nothing replaces
  them. Anything referencing them breaks.
* **`Session energy` is now `total_increasing`** instead of `measurement`.
  Long term statistics for that sensor start over; the recorded history is
  kept.

The integration also requires the `bleak-retry-connector` package, which Home
Assistant installs automatically, and Home Assistant 2025.2 or newer.

## Entities

| Domain | Entities |
| --- | --- |
| `switch` | Charging, Start from charger button |
| `sensor` | Connection, Status, Plug state, Voltage L1–L3, Current L1–L3, Power, Total energy, Internal and external temperature, Session energy, duration, start, current limit, user, ID and cost, Last record energy, end, duration and stop reason |
| `binary_sensor` | Plugged in, Charging, Problem, Emergency stop, Weekly plan active |
| `number` | Charging current, and three optional session limits |
| `select` | Display temperature unit |
| `button` | Start charging, Stop charging, Sync clock, Re-send Wi-Fi settings |
| Diagnostics | Phases, rated current and power, charger clock and drift, charging port, Wi-Fi network, raw protocol fields |

`Status` and `Plug state` are `enum` sensors with translated states, usable in
automations without matching English text. `Total energy` and `Session energy`
are `total_increasing`, so both work in the Energy dashboard.

New entity IDs are `<domain>.besen_<serial>_<english_key>` regardless of the
Home Assistant interface language; only the displayed names are translated.
Entities carried over from 1.x keep the IDs they already have.

## Installation

Install through [HACS](https://hacs.xyz/) as a custom repository, or copy
`custom_components/besen` into your Home Assistant `custom_components` folder
and restart.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sustainabledeveloper&repository=bs20&category=integration)

## Setup

Before adding the integration:

1. Pair the charger with the EVSEMaster app over Bluetooth.
2. Set up Wi-Fi for the charger in the app.
3. Restart the app and confirm it reaches the charger over Wi-Fi.
4. Put Home Assistant on the same network as the charger.
5. Leave UDP port 28376 free.

Then add the integration and enter:

* **Serial number** — 16 hexadecimal digits, shown in the EVSEMaster app.
* **Charger password** — exactly 6 characters, `123456` unless changed.

Both are fixed length, so the form rejects anything that would not fit. The
charger's IP address is discovered automatically.

In Docker, publish the port:

```yaml
ports:
  - "28376:28376/udp"
```

Entities appear immediately and fill in within a few seconds, as soon as the
charger's next broadcast arrives.

Several chargers can be added; each is matched by its serial number.

## Upgrading from 1.x

The domain is unchanged, so existing config entries are kept and there is no
need to remove and re-add anything. On first start the entry is migrated:

* Entity unique IDs move to `<serial>_<snake_case>`.
* **Entity IDs are left exactly as they are**, so dashboards, automations and
  recorded history keep working.
* Labels that 1.x wrote into the entity registry are cleared so the translated
  names apply. A name you set yourself is left alone.
* Entities with no replacement (`Unknown 1`–`Unknown 4`) are removed.
* The device registry entry is re-keyed from a placeholder identifier to the
  integration domain.

Two things do change behaviour:

* **`Charging power` now reports the total across all phases.** On a three
  phase charger the firmware reports one phase, so the old value was a third of
  the truth. The raw field is still available as a disabled diagnostic sensor.
* **`Session energy` changed from `measurement` to `total_increasing`,** which
  is what the Energy dashboard needs. Long term statistics for it start over.

If HACS leaves the old `custom_components/bs20` folder behind after the update,
delete it and restart; otherwise Home Assistant will try to load the
integration twice.

## Options

Reachable from **Settings → Devices & services → Besen → Configure**.

| Option | Default | Effect |
| --- | --- | --- |
| Keep the charger's clock in sync | on | Writes the correct time whenever the charger comes online. Nothing else corrects this clock, and every timestamp the charger reports depends on it. |
| Reach the charger over Bluetooth when Wi-Fi is down | off | See below. |
| Bluetooth address | empty | Match by advertised name unless set. |
| Acknowledge uploaded charging records | off | See below. |
| Wi-Fi network name and password | empty | Used by the Wi-Fi recovery below. |
| Re-send Wi-Fi settings automatically | off | See below. |

## Bluetooth

Some chargers fail to rejoin Wi-Fi after a power cut, and the only way back is
Bluetooth. With **Reach the charger over Bluetooth when Wi-Fi is down** enabled,
Home Assistant keeps using Wi-Fi normally and connects over Bluetooth only after
the charger has been silent for two minutes, releasing the link as soon as the
charger reappears on the network. These chargers accept one connection at a
time, so holding it would lock the phone app out.

The `Connection` sensor reports which transport is carrying traffic — `wifi`,
`bluetooth` or `none` — and never becomes unavailable.

Requirements:

* A Bluetooth adapter or an ESPHome Bluetooth proxy **within range of the
  charger**. For a wallbox in a garage that usually means a proxy nearby rather
  than the Home Assistant host.
* The phone app must not be holding the link. Close it, or turn the phone's
  Bluetooth off, before expecting Home Assistant to connect.

### Choosing the device

Nothing to pick by hand in the normal case. When a charger comes into range,
Home Assistant offers it as a discovered device; accepting it asks for the full
serial number and the charger password and stores the Bluetooth address with the
entry. A charger that is already configured is not offered again, its address is
simply filled in.

With several chargers the advertised name can collide: it carries only the last
two bytes of the serial, so `1122334455667788` and `AABBCCDDEEFF7788` both
advertise as `ACP#EVSE7788`. The integration then refuses to guess, logs which
chargers the name could mean, and leaves the address unset — put the right one
into **Bluetooth address** in that charger's options.

The name is only ever a hint. The charger identifies itself fully once
connected, so a connection that lands on the wrong one is dropped and logged
rather than reporting another unit's readings.

## Wi-Fi recovery

Fill in the network name and password in the options and enable **Re-send Wi-Fi
settings automatically**. When Bluetooth reaches a charger that has gone quiet,
the credentials are written back once per outage — the repair that otherwise
means pairing with the phone app by hand.

There is also a `Re-send Wi-Fi settings` button, disabled by default, for doing
it deliberately. It stays pressable while the charger is unreachable.

The passphrase is stored with the config entry and redacted from diagnostics. It
is dropped from the charger's own answer rather than kept, so it never reaches
the state machine or the recorder.

The `Wi-Fi network` sensor reports the network the charger confirmed after such
a write. Nothing else makes the charger name its network, so it stays unknown
otherwise and ships disabled; enable it if you want the confirmation.

## Charging records

When a session ends the charger uploads a record and keeps rebroadcasting it
until an app confirms it. Each new record is published on the event bus as
`besen_charge_record` and the most recent one is exposed as sensors:

```yaml
automation:
  - alias: Log finished charging sessions
    triggers:
      - trigger: event
        event_type: besen_charge_record
    actions:
      - action: logbook.log
        data:
          name: EV charger
          message: >-
            {{ trigger.event.data.energy }} kWh in
            {{ (trigger.event.data.duration / 3600) | round(1) }} h,
            stopped by {{ trigger.event.data.stop_reason }}
```

**Acknowledge uploaded charging records** stops the repeats and drains whatever
backlog the charger is holding — twenty stored sessions in one minute is normal
on a charger that has never been acknowledged. It is off by default because the
queue is shared: a record acknowledged here may be dropped before the EVSEMaster
app has downloaded it. Every record is published as an event *before* it is
acknowledged, so nothing is lost on the Home Assistant side.

## Session limits

`Charging current` is applied immediately and follows the charger's own rated
current, read from the charger rather than assumed.

Note that this charger cannot change current mid-session without interrupting
it: setting a new value stops charging for roughly twenty seconds. Solar or
tariff automations should change it in steps, not continuously.

The three **session limit** numbers (duration, energy, cost) are written into
the start command. Their wire units are not confirmed, so they are **disabled by
default** and `0` means unlimited, which is the behaviour without them.

## Energy dashboard

Add `Total energy` under **Individual devices**. It is the charger's lifetime
meter and it is `total_increasing`, which is what the dashboard needs.

`Session energy` is also `total_increasing` and will be offered too. Pick one
or the other: adding both counts the same kilowatt hours twice.

## MQTT and evcc

There is no MQTT support in the integration. Home Assistant's
[mqtt_statestream](https://www.home-assistant.io/integrations/mqtt_statestream)
publishes every entity to a broker, and
[MQTT triggers](https://www.home-assistant.io/docs/automation/trigger/#mqtt-trigger)
drive them the other way, which is enough to present the charger to evcc as a
generic wallbox.

## Troubleshooting

**Start here: download diagnostics** from Settings → Devices & services → Besen
→ ⋮ → Download diagnostics. It reports the integration version, the options in
use, every decoded field, and for Bluetooth: how many adapters exist, which
chargers are in range and at what signal, whether an attempt is queued, how many
have run, and what the last one failed with. Credentials are redacted.

**No data at all.** Check that the charger reaches the same network as Home
Assistant:

```bash
sudo tcpdump -i any -X 'udp port 28376'
```

You should see a datagram from the charger every few seconds. The source port
varies between firmware versions, so do not filter on it.

**Data only arrives while the phone app is open.** Fixed in 2.0.0. Earlier
releases learned the charger's address only from a login broadcast that many
firmwares never send, so no acknowledgement was ever returned and the charger
stopped sending.

**Commands do nothing.** Check the serial number and password. A wrong password
is accepted by the charger's receiver but the command is ignored. The log says
`Cannot send command ... has not been heard from yet` when the address is not
known yet.

**Two chargers show each other's readings.** Fixed in 2.0.0.

**`Invalid handler specified` when adding the integration.** Fixed in 2.0.0; the
folder name and the integration domain now match.

**Bluetooth connects but no data arrives.** Download diagnostics and open an
issue with it attached; it records enough about the link to tell where it
stopped.

**An entity was renamed by the upgrade.** A pre-release of 2.0.0 could move an
entity that 1.x had labelled differently in an earlier release onto the current
label's ID: `Session energy` in particular could move from
`..._currently_charged_power` to `..._currently_charged_amount`. Fixed, but an
ID that already moved has to be put back by hand: Settings →
Devices & services → Besen → the entity → the gear icon → Entity ID. The old
ID left behind in the state machine, the one warning that it has no unique ID,
disappears at the next restart.

**Some values are missing.** Sensors that stay unavailable usually mean a
different firmware reporting less. Open an issue with the diagnostics download
attached.

### Debug logging

Settings → Devices & services → Besen → ⋮ → Enable debug logging, or:

```yaml
logger:
  logs:
    custom_components.besen: debug
```

Note that the Logs page shows only warnings and errors until **Load full logs**
is used.

## Tools

Three standalone scripts, none of which need Home Assistant:

```bash
python3 tools/besen_probe.py --seconds 60              # watch UDP traffic
python3 tools/besen_ble_probe.py --connect             # read the GATT table
python3 tools/besen_session_watch.py --serial <hex>    # follow a charging session
```

`besen_probe.py` can also answer the charger when given `--active`, using only
acknowledgements and read-only queries; it never sends a command that changes
anything. `besen_ble_probe.py` only scans, reads and listens.

## Change log

### 2.0.0

* Fixed per-charger state so several chargers no longer overwrite each other's
  readings, and reloading no longer leaves stale entities behind.
* Messages are validated and matched to the right charger before use.
* The charger's address is learned from everything it sends, not only from an
  announcement many firmwares never make. This is what made data arrive only
  while the phone app was open.
* Fixed the status sensor, which reported `--` permanently.
* Fixed start and stop, which sent a malformed command.
* `Charging power` now sums the phases instead of reporting a third of the
  truth on a three phase charger.
* Session energy is `total_increasing`, so the Energy dashboard accepts it.
* Timestamps are real `timestamp` sensors and show the right time.
* Charging current follows the charger's rated current instead of a fixed 32 A.
* Device information comes from the charger instead of hard coded strings.
* Added `switch.charging`, five binary sensors, a display unit select, clock
  sync, charging record support, diagnostics, English and Hungarian
  translations, and reconfigure and reauth flows.
* Added a Bluetooth fallback with device discovery, and Wi-Fi recovery for
  chargers that cannot rejoin the network.
* Entity IDs no longer depend on the interface language, and the upgrade keeps
  the IDs 1.x created, including those from releases that later renamed their
  labels.
* The Wi-Fi network name is redacted from the diagnostics download.
* Renamed the integration folder to match its domain, which fixes
  `Invalid handler specified`.

### 1.0.3

* Energy dashboard support.
* Device serial prefix for entity IDs.

### 1.0.2

* Start/stop charging and setting the charging power.

### 1.0.1

* Improved sensor updates.

## Support

Issues and suggestions: <https://github.com/sustainabledeveloper/BS20/issues>
