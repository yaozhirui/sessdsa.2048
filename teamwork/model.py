class Player:

    def __init__(self: Player, isFirst: bool, array: tuple[int]) -> None:
        pass

    def output(self: Player, currentRound: int, board: Chessboard, mode: str) -> Union[Tuple[int, int], int]:
        pass

class Chessboard:

    def __init__(self: Chessboard, array: tuple[int]) -> None: 
        pass

    def add(self: Chessboard, belong: bool, position: Tuple[int, int], value: int = 1) -> None:
        pass

    def move(self: Chessboard, belong: bool, direction: int) -> bool:
        pass

    def getBelong(self: Chessboard, position: Tuple[int, int]) -> bool:
        pass

    def getValue(self: Chessboard, position: Tuple[int, int]) -> int:
        pass

    def getScore(self: Chessboard, belong: bool) -> List[int]:
        pass

    def getNone(self: Chessboard, belong: bool) -> List[Tuple[int, int]]:
        pass

    def getNext(self: Chessboard, belong: bool, currentRound) -> Union[Tuple[int, int], Tuple[]]:
        pass

    def copy(self: Chessboard) -> Chessboard:
        pass

    def __repr__(self: Chessboard) -> str:
        pass

    __str__ = __repr__

    def getTime(self: Chessboard) -> float:
        pass

    def updateTime(self: Chessboard, belong: bool, time: float) -> None:
        pass

    def getDecision(self: Chessboard, belong: bool) -> Union[Tuple[], Tuple[int, int], Tuple[int]]:
        pass

    def getAnime(self: Chessboard) -> Any:
        pass


