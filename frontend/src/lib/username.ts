export const USERNAME_MIN_LENGTH = 4;
export const USERNAME_MAX_LENGTH = 16;
export const USERNAME_PATTERN = /^[a-z0-9]{4,16}$/;
export const USERNAME_VALIDATION_MESSAGE = `Username must be ${USERNAME_MIN_LENGTH}-${USERNAME_MAX_LENGTH} characters and contain only lowercase letters and numbers`;

export function sanitizeUsernameInput(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, USERNAME_MAX_LENGTH);
}

export function isValidUsername(username: string): boolean {
  return USERNAME_PATTERN.test(username);
}
