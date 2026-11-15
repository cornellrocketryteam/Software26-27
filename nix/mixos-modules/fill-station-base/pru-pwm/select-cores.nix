profile:
let
  outputs = builtins.concatLists (map
    (device: if device.enabled then builtins.attrValues device.connections else [ ])
    profile.devices);
  matches = builtins.filter (value: value != null)
    (map (connection: builtins.match "PRG0_PRU([01])_GPO[0-9]+" connection.function) outputs);
in
builtins.filter (core: builtins.any (match: builtins.head match == toString core) matches) [ 0 1 ]
