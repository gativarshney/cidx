class Temperature {
  static zero = new Temperature(0);

  constructor(private celsius: number) {}

  get fahrenheit(): number {
    return convert(this.celsius);
  }

  set fahrenheit(value: number) {
    this.celsius = invert(value);
  }

  static origin(): Temperature {
    return Temperature.zero;
  }
}
