namespace Validation {
  export function isEmail(s: string): boolean {
    return pattern.test(s);
  }
}
