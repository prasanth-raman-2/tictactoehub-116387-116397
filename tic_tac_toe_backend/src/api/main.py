from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
import uuid


# -------------------------------------------
# PUBLIC_INTERFACE
class NewGameRequest(BaseModel):
    player_x: str = Field(..., description="Username of Player X")
    player_o: str = Field(..., description="Username of Player O")


# PUBLIC_INTERFACE
class MoveRequest(BaseModel):
    player: str = Field(..., description="Player's username making the move")
    row: int = Field(..., ge=0, le=2, description="Row number (0-2)")
    col: int = Field(..., ge=0, le=2, description="Col number (0-2)")


# PUBLIC_INTERFACE
class BoardState(BaseModel):
    board: List[List[Optional[Literal["X", "O"]]]] = Field(
        ..., description="3x3 game board"
    )
    next_turn: Optional[str] = Field(
        None, description="Which player's turn username, or None if finished"
    )
    winner: Optional[str] = Field(
        None, description="Username of winner, or None if not decided"
    )
    draw: bool = Field(False, description="Whether the game is a draw")
    status: Literal["waiting", "playing", "finished"] = Field(
        ..., description="Game status"
    )
    player_x: str = Field(..., description="Player X")
    player_o: str = Field(..., description="Player O")


# PUBLIC_INTERFACE
class GameInfo(BaseModel):
    game_id: str = Field(..., description="ID of the game")
    board_state: BoardState


# PUBLIC_INTERFACE
class LeaderboardEntry(BaseModel):
    player: str = Field(..., description="Player username")
    wins: int = Field(..., description="Number of wins")
    games_played: int = Field(..., description="Total number of games played")


# ---- IN-MEMORY DATA STORES (Placeholder for DB) ----
games_store: Dict[str, Dict[str, Any]] = {}
leaderboard_store: Dict[str, Dict[str, int]] = {}  # player -> {"wins": int, "games_played": int}
past_games: List[Dict[str, Any]] = []  # For game history / leaderboard


# ---- UTILITY FUNCTIONS ----
def empty_board() -> List[List[Optional[str]]]:
    """Return a 3x3 board filled with None."""
    return [[None for _ in range(3)] for _ in range(3)]


def check_winner(board: List[List[Optional[str]]]) -> Optional[str]:
    """Return 'X', 'O', or None based on board contents."""
    # Rows, cols, diagonals
    for i in range(3):
        if board[i][0] and all(board[i][j] == board[i][0] for j in range(3)):
            return board[i][0]
        if board[0][i] and all(board[j][i] == board[0][i] for j in range(3)):
            return board[0][i]
    # Diags
    if board[0][0] and all(board[i][i] == board[0][0] for i in range(3)):
        return board[0][0]
    if board[0][2] and all(board[i][2 - i] == board[0][2] for i in range(3)):
        return board[0][2]
    return None


def is_full(board: List[List[Optional[str]]]) -> bool:
    """Check if the board is full."""
    return all(all(s is not None for s in row) for row in board)


def create_board_state(game: Dict[str, Any]) -> BoardState:
    winner = game['winner']
    draw = game['draw']
    status = game['status']
    return BoardState(
        board=game["board"],
        next_turn=game["next_turn"] if status == "playing" else None,
        winner=winner,
        draw=draw,
        status=status,
        player_x=game["player_x"],
        player_o=game["player_o"]
    )


def save_leaderboard(player: str, won: bool):
    if player not in leaderboard_store:
        leaderboard_store[player] = {"wins": 0, "games_played": 0}
    leaderboard_store[player]["games_played"] += 1
    if won:
        leaderboard_store[player]["wins"] += 1


def finalize_game_stats(game: Dict[str, Any]):
    # both players get a game played; winner gets win
    save_leaderboard(game["player_x"], won=game["winner"] == game["player_x"])
    save_leaderboard(game["player_o"], won=game["winner"] == game["player_o"])
    # Save to simple history storage
    past_games.append({
        "game_id": game["game_id"],
        "player_x": game["player_x"],
        "player_o": game["player_o"],
        "winner": game["winner"],
        "draw": game["draw"],
    })


# ---- FASTAPI APP AND ROUTES ----

app = FastAPI(
    title="Tic Tac Toe Backend API",
    version="1.0.0",
    description="Backend API for playing Tic Tac Toe, leaderboards, and game state management"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", summary="Health check")
def health_check():
    """Health check endpoint."""
    return {"message": "Healthy"}


# PUBLIC_INTERFACE
@app.post(
    "/games",
    response_model=GameInfo,
    summary="Create a new game",
    tags=["Games"],
    description="Start a new Tic Tac Toe game with two players."
)
def create_game(data: NewGameRequest = Body(...)):
    game_id = str(uuid.uuid4())
    board = empty_board()
    # Start with X's turn
    game = {
        "game_id": game_id,
        "player_x": data.player_x,
        "player_o": data.player_o,
        "next_turn": data.player_x,
        "last_turn_symbol": None,
        "board": board,
        "winner": None,
        "draw": False,
        "status": "playing"  # or 'finished'
    }
    games_store[game_id] = game
    return GameInfo(game_id=game_id, board_state=create_board_state(game))


# PUBLIC_INTERFACE
@app.get(
    "/games/{game_id}",
    response_model=GameInfo,
    summary="Get current game state",
    tags=["Games"],
    description="Fetches the current board and status for a game."
)
def get_game(game_id: str):
    game = games_store.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return GameInfo(game_id=game_id, board_state=create_board_state(game))


# PUBLIC_INTERFACE
@app.post(
    "/games/{game_id}/move",
    response_model=GameInfo,
    summary="Submit a move",
    tags=["Games"],
    description="Submit a player's move at (row, col)."
)
def make_move(game_id: str, move: MoveRequest = Body(...)):
    game = games_store.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    if game["status"] != "playing":
        raise HTTPException(status_code=400, detail="Game already finished")

    if game["winner"] or game["draw"]:
        raise HTTPException(status_code=400, detail="Game ended")

    if move.player not in [game["player_x"], game["player_o"]]:
        raise HTTPException(status_code=400, detail="Unknown player for this game")

    symbol = "X" if move.player == game["player_x"] else "O"
    # Enforce turn
    if game["next_turn"] != move.player:
        raise HTTPException(status_code=400, detail="Not this player's turn")
    # Validate cell
    if not (0 <= move.row < 3 and 0 <= move.col < 3):
        raise HTTPException(status_code=400, detail="Invalid board index")
    if game["board"][move.row][move.col] is not None:
        raise HTTPException(status_code=400, detail="Cell already occupied")
    # Place the move
    game["board"][move.row][move.col] = symbol
    game["last_turn_symbol"] = symbol
    # Next turn logic
    next_player = game["player_o"] if move.player == game["player_x"] else game["player_x"]

    # Check for win condition
    winner_symbol = check_winner(game["board"])
    if winner_symbol:
        game["winner"] = game["player_x"] if winner_symbol == "X" else game["player_o"]
        game["status"] = "finished"
        game["next_turn"] = None
        finalize_game_stats(game)
    elif is_full(game["board"]):
        game["draw"] = True
        game["status"] = "finished"
        game["next_turn"] = None
        finalize_game_stats(game)
    else:
        game["next_turn"] = next_player

    return GameInfo(game_id=game_id, board_state=create_board_state(game))


# PUBLIC_INTERFACE
@app.get(
    "/leaderboard",
    response_model=List[LeaderboardEntry],
    summary="Get leaderboard",
    tags=["Leaderboard"],
    description="Gets the current leaderboard showing wins and total games per player."
)
def get_leaderboard():
    # Sort by wins DESC, then games_played DESC, then name
    sorted_leaderboard = sorted(
        leaderboard_store.items(),
        key=lambda kv: (-kv[1]["wins"], -kv[1]["games_played"], kv[0])
    )
    return [
        LeaderboardEntry(player=name, wins=data["wins"], games_played=data["games_played"])
        for name, data in sorted_leaderboard
    ]


# PUBLIC_INTERFACE
@app.get(
    "/past-games",
    response_model=List[Dict[str, Any]],
    summary="Get past games",
    tags=["Games"],
    description="Fetch a listing of past finished games with players and results."
)
def get_past_games():
    return past_games[-50:]  # Last 50 (very simple, demo only)
