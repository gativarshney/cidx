class Outer:
    class Inner:
        def method(self) -> None:
            pass

    def make(self) -> "Outer.Inner":
        def build():
            return Outer.Inner()

        return build()
