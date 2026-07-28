@injectable()
class Repository extends BaseRepo implements Store {
  limit = 100;
  handler = (e: Event) => this.process(e);

  constructor(private db: Database) {
    super();
  }

  async save(user: User): Promise<void> {
    await this.db.write(user);
  }

  private process(e: Event): void {
    validate(e);
  }
}
