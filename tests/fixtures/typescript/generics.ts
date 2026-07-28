class Store<T extends Item> extends BaseStore<T> {
  add(entry: T): void {
    this.validate(entry);
  }
}

function identity<T>(value: T): T {
  return value;
}

const store = new Store<Item>();
