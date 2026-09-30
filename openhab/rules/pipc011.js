// openHAB 5, JavaScript Scripting (automation/js/pipc011.js)
// Examples – the camera logic itself lives in the MQTT bridge,
// rules only link events in the building to camera commands.

// Motion detected -> log a timestamp (the bridge takes the snapshot itself
// if mqtt.snapshot_on_motion=true)
rules.JSRule({
  name: "PIPC-011: Motion",
  triggers: [triggers.ItemStateChangeTrigger("Cam_Motion", "CLOSED", "OPEN")],
  execute: () => {
    console.info("PIPC-011: motion detected");
  }
});

// After working hours go to preset 2 (e.g. view of the lab entrance), back to 1 in the morning
rules.JSRule({
  name: "PIPC-011: Preset by time of day",
  triggers: [
    triggers.GenericCronTrigger("0 0 18 ? * MON-FRI"),
    triggers.GenericCronTrigger("0 0 7 ? * MON-FRI")
  ],
  execute: () => {
    const evening = time.ZonedDateTime.now().hour() >= 12;
    items.Cam_Preset.sendCommand(evening ? 2 : 1);
  }
});
