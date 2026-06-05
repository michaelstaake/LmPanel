type DeviceIdentityLike = {
  display_suffix: string;
};

export function formatDeviceIdLabel(device: DeviceIdentityLike) {
  return `ID ${device.display_suffix}`;
}