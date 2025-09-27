"""
Tk Chess — Human (White) vs Computer (Black)

Tech
- Python 3.x
- Tkinter for GUI (bundled with Python)
- python-chess for rules & validation (pip install python-chess)

Features
- Standard 8x8 board with proper starting setup
- White is human (click piece then destination). Black is computer.
- Only legal moves allowed (castling, en passant, promotions handled)
- Highlights: selected square, available legal moves, last move
- Captured pieces shown for both sides
- Move history (SAN)
- Restart Game / Save PGN / Load PGN
- Difficulty selector (AI depth 1..4). Depth 2–3 is a nice balance.

AI
- Alpha-beta search with move ordering (captures first, PV first)
- Simple evaluation: material + piece-square tables + mobility + checkmate/stalemate handling
- Computer auto-queens promotions (rare underpromotions not considered)

No internet required.
"""

import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import threading
import random
import math
import sys
import time

try:
    import chess
    import chess.pgn
except ImportError:
    raise SystemExit("Missing dependency: python-chess\nInstall:\n    pip install python-chess")

# ------------------ Simple Engine ------------------ #
# Basic piece values and piece-square tables (middlegame-ish)
PIECE_VALUES = {
    chess.PAWN:   100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK:   500,
    chess.QUEEN:  900,
    chess.KING:   0,
}

# Piece-square tables (from White's perspective). Black uses mirrored tables.
# Values are small; they nudge the search.
# Source inspiration: common PSTs (slightly simplified).
PAWN_PST = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]
KNIGHT_PST = [
   -50,-40,-30,-30,-30,-30,-40,-50,
   -40,-20,  0,  5,  5,  0,-20,-40,
   -30,  5, 10, 15, 15, 10,  5,-30,
   -30,  0, 15, 20, 20, 15,  0,-30,
   -30,  5, 15, 20, 20, 15,  5,-30,
   -30,  0, 10, 15, 15, 10,  0,-30,
   -40,-20,  0,  0,  0,  0,-20,-40,
   -50,-40,-30,-30,-30,-30,-40,-50,
]
BISHOP_PST = [
   -20,-10,-10,-10,-10,-10,-10,-20,
   -10,  5,  0,  0,  0,  0,  5,-10,
   -10, 10, 10, 10, 10, 10, 10,-10,
   -10,  0, 10, 10, 10, 10,  0,-10,
   -10,  5,  5, 10, 10,  5,  5,-10,
   -10,  0,  5, 10, 10,  5,  0,-10,
   -10,  0,  0,  0,  0,  0,  0,-10,
   -20,-10,-10,-10,-10,-10,-10,-20,
]
ROOK_PST = [
     0,  0,  5, 10, 10,  5,  0,  0,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     5, 10, 10, 10, 10, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]
QUEEN_PST = [
   -20,-10,-10, -5, -5,-10,-10,-20,
   -10,  0,  5,  0,  0,  0,  0,-10,
   -10,  5,  5,  5,  5,  5,  0,-10,
    -5,  0,  5,  5,  5,  5,  0, -5,
     0,  0,  5,  5,  5,  5,  0, -5,
   -10,  0,  5,  5,  5,  5,  0,-10,
   -10,  0,  0,  0,  0,  0,  0,-10,
   -20,-10,-10, -5, -5,-10,-10,-20,
]
KING_PST = [
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -30,-40,-40,-50,-50,-40,-40,-30,
   -20,-30,-30,-40,-40,-30,-30,-20,
   -10,-20,-20,-20,-20,-20,-20,-10,
    20, 20,  0,  0,  0,  0, 20, 20,
    20, 30, 10,  0,  0, 10, 30, 20,
]

PST = {
    chess.PAWN:   PAWN_PST,
    chess.KNIGHT: KNIGHT_PST,
    chess.BISHOP: BISHOP_PST,
    chess.ROOK:   ROOK_PST,
    chess.QUEEN:  QUEEN_PST,
    chess.KING:   KING_PST,
}

def pst_value(piece_type, square, color_is_white):
    idx = square if color_is_white else chess.square_mirror(square)
    return PST[piece_type][idx]

def evaluate(board: chess.Board) -> int:
    """Positive = good for White; Negative = good for Black."""
    # Terminal checks
    if board.is_checkmate():
        return 10_000 if board.turn == chess.BLACK else -10_000  # side to move is checkmated
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score = 0
    pm = board.piece_map()
    for sq, piece in pm.items():
        base = PIECE_VALUES[piece.piece_type]
        pst = pst_value(piece.piece_type, sq, piece.color == chess.WHITE)
        val = base + pst
        score += val if piece.color == chess.WHITE else -val

    # Mobility (small)
    board_turn = board.turn
    board.turn = chess.WHITE
    w_mob = board.legal_moves.count()
    board.turn = chess.BLACK
    b_mob = board.legal_moves.count()
    board.turn = board_turn
    score += 2 * (w_mob - b_mob)

    # Tiny random jitter to avoid deterministic lines
    score += random.randint(-2, 2)
    return score

def order_moves(board: chess.Board, moves):
    """Move ordering: captures first, then checks if fast to test."""
    def score_move(m: chess.Move):
        s = 0
        if board.is_capture(m):
            victim = board.piece_at(m.to_square)
            attacker = board.piece_at(m.from_square)
            if victim and attacker:
                s += 10 * PIECE_VALUES[victim.piece_type] - PIECE_VALUES[attacker.piece_type]
            else:
                s += 500
        # Prefer promotions
        if m.promotion:
            s += 800 + PIECE_VALUES.get(m.promotion, 0)
        # Prefer checks
        board.push(m)
        if board.is_check():
            s += 80
        board.pop()
        return -s  # ascending sort uses negative for descending priority
    return sorted(moves, key=score_move)

def alpha_beta(board: chess.Board, depth: int, alpha: int, beta: int) -> int:
    if depth == 0 or board.is_game_over():
        return evaluate(board)

    if board.turn == chess.WHITE:
        value = -math.inf
        for m in order_moves(board, list(board.legal_moves)):
            board.push(m)
            value = max(value, alpha_beta(board, depth - 1, alpha, beta))
            board.pop()
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return value
    else:
        value = math.inf
        for m in order_moves(board, list(board.legal_moves)):
            board.push(m)
            value = min(value, alpha_beta(board, depth - 1, alpha, beta))
            board.pop()
            beta = min(beta, value)
            if beta <= alpha:
                break
        return value

def find_best_move(board: chess.Board, depth: int) -> chess.Move:
    """Return a move for the side to move (Black in our GUI after White goes)."""
    best = None
    if board.turn == chess.WHITE:
        best_val = -math.inf
        for m in order_moves(board, list(board.legal_moves)):
            board.push(m)
            val = alpha_beta(board, depth - 1, -math.inf, math.inf)
            board.pop()
            if val > best_val + 1 or (abs(val - best_val) <= 1 and random.random() < 0.25):
                best_val = val
                best = m
    else:
        best_val = math.inf
        for m in order_moves(board, list(board.legal_moves)):
            board.push(m)
            val = alpha_beta(board, depth - 1, -math.inf, math.inf)
            board.pop()
            if val < best_val - 1 or (abs(val - best_val) <= 1 and random.random() < 0.25):
                best_val = val
                best = m
    # Fallback (shouldn’t happen)
    return best or random.choice(list(board.legal_moves))

# ------------------ GUI ------------------ #
class ChessGUI:
    BOARD_SIZE = 8
    SQUARE_PX = 72
    MARGIN = 12

    LIGHT_COLOR = "#F0D9B5"
    DARK_COLOR = "#B58863"
    HIGHLIGHT_SEL = "#88CCFF"
    HIGHLIGHT_MOVE = "#8FDE5D"
    HIGHLIGHT_LAST = "#F6F669"

    PIECES = {
        (chess.PAWN,   True): "♙", (chess.KNIGHT, True): "♘",
        (chess.BISHOP, True): "♗", (chess.ROOK,   True): "♖",
        (chess.QUEEN,  True): "♕", (chess.KING,   True): "♔",
        (chess.PAWN,  False): "♟", (chess.KNIGHT, False): "♞",
        (chess.BISHOP,False): "♝", (chess.ROOK,  False): "♜",
        (chess.QUEEN, False): "♛", (chess.KING,  False): "♚",
    }

    PROMO_CHOICES = [
        ("Queen", chess.QUEEN, "Q"),
        ("Rook", chess.ROOK, "R"),
        ("Bishop", chess.BISHOP, "B"),
        ("Knight", chess.KNIGHT, "N"),
    ]

    def __init__(self, root):
        self.root = root
        root.title("Tk Chess — You (White) vs Computer (Black)")

        # Chess state
        self.board = chess.Board()
        self.selected_sq = None
        self.legal_dests_for_selected = set()
        self.last_move = None
        self.white_captured = []
        self.black_captured = []
        self.move_san_list = []

        # AI settings/state
        self.ai_depth = tk.IntVar(value=3)  # difficulty
        self.ai_working = False
        self.ai_thread = None

        # Layout
        self.container = tk.Frame(root, padx=10, pady=10)
        self.container.pack(fill="both", expand=True)

        self.left_panel = tk.Frame(self.container)
        self.left_panel.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        self.center_panel = tk.Frame(self.container)
        self.center_panel.grid(row=0, column=1, sticky="nsew")
        self.right_panel = tk.Frame(self.container)
        self.right_panel.grid(row=0, column=2, sticky="ns", padx=(8, 0))

        self.container.columnconfigure(1, weight=1)
        self.container.rowconfigure(0, weight=1)

        canvas_px = self.BOARD_SIZE * self.SQUARE_PX + self.MARGIN * 2
        self.canvas = tk.Canvas(
            self.center_panel, width=canvas_px, height=canvas_px, highlightthickness=0
        )
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Configure>", lambda e: self.redraw())

        # Left panel
        tk.Label(self.left_panel, text="Captured by White (black pieces)", font=("Arial", 12, "bold")).pack(pady=(0, 6))
        self.lbl_captured_black = tk.Label(self.left_panel, text="", font=("Segoe UI Symbol", 20))
        self.lbl_captured_black.pack()

        # Right panel controls
        tk.Label(self.right_panel, text="Controls", font=("Arial", 12, "bold")).pack(anchor="w")
        btns = tk.Frame(self.right_panel)
        btns.pack(fill="x", pady=(2, 10))
        tk.Button(btns, text="Restart Game", command=self.restart).pack(fill="x")
        tk.Button(btns, text="Save PGN", command=self.save_pgn).pack(fill="x", pady=(6,0))
        tk.Button(btns, text="Load PGN", command=self.load_pgn).pack(fill="x", pady=(6,12))

        diff = tk.Frame(self.right_panel)
        diff.pack(fill="x", pady=(0, 10))
        tk.Label(diff, text="Computer strength:").pack(anchor="w")
        ttk.Spinbox(diff, from_=1, to=4, textvariable=self.ai_depth, width=5, state="readonly").pack(anchor="w")
        tk.Label(diff, text="(1=fast, 4=stronger)", fg="#555").pack(anchor="w")

        # Move history
        tk.Label(self.right_panel, text="Move History", font=("Arial", 12, "bold")).pack(anchor="w")
        self.history = tk.Text(self.right_panel, width=24, height=20, state="disabled", font=("Consolas", 11))
        self.history.pack(fill="both", expand=True, pady=(2, 10))

        tk.Label(self.right_panel, text="Captured by Black (white pieces)", font=("Arial", 12, "bold")).pack(anchor="w")
        self.lbl_captured_white = tk.Label(self.right_panel, text="", font=("Segoe UI Symbol", 20))
        self.lbl_captured_white.pack(anchor="w")

        # “Computer thinking” badge
        self.thinking_badge = tk.Label(self.center_panel, text="", bg="#333", fg="#fff", padx=10, pady=4)

        self.redraw()
        self.maybe_trigger_ai()

    # ---------- Drawing ----------
    def redraw(self):
        self.canvas.delete("all")
        cw = max(self.canvas.winfo_width(), self.BOARD_SIZE * self.SQUARE_PX // 2)
        ch = max(self.canvas.winfo_height(), self.BOARD_SIZE * self.SQUARE_PX // 2)
        board_px = min(cw, ch) - self.MARGIN * 2
        sq = board_px // self.BOARD_SIZE
        self._current_square_px = sq
        start_x = (cw - (sq * self.BOARD_SIZE)) // 2
        start_y = (ch - (sq * self.BOARD_SIZE)) // 2
        self._origin = (start_x, start_y)

        # Squares
        for r in range(self.BOARD_SIZE):
            for f in range(self.BOARD_SIZE):
                x0 = start_x + f * sq
                y0 = start_y + r * sq
                x1 = x0 + sq
                y1 = y0 + sq
                light = (r + f) % 2 == 0
                fill = self.LIGHT_COLOR if light else self.DARK_COLOR
                self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=fill, tags="square")

        # Last move
        if self.last_move is not None:
            for sqi in [self.last_move.from_square, self.last_move.to_square]:
                rx0, ry0, rx1, ry1 = self._square_rect(sqi, sq)
                self.canvas.create_rectangle(rx0, ry0, rx1, ry1, fill=self.HIGHLIGHT_LAST, outline="")

        # Selected + legal dots
        if self.selected_sq is not None:
            sx0, sy0, sx1, sy1 = self._square_rect(self.selected_sq, sq)
            self.canvas.create_rectangle(sx0, sy0, sx1, sy1, outline=self.HIGHLIGHT_SEL, width=4)
            for dest in sorted(self.legal_dests_for_selected):
                dx0, dy0, dx1, dy1 = self._square_rect(dest, sq)
                cx = (dx0 + dx1) / 2
                cy = (dy0 + dy1) / 2
                radius = sq * 0.18
                self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                                        fill=self.HIGHLIGHT_MOVE, outline="")

        # Pieces
        for square, piece in self.board.piece_map().items():
            px0, py0, px1, py1 = self._square_rect(square, sq)
            cx = (px0 + px1) / 2
            cy = (py0 + py1) / 2
            char = self.PIECES[(piece.piece_type, piece.color)]
            font_size = int(sq * 0.65)
            self.canvas.create_text(cx, cy, text=char, font=("Segoe UI Symbol", font_size))

        # Coordinates
        self._draw_coords_labels(sq, start_x, start_y)

        self.lbl_captured_black.config(text="".join(self.black_captured))
        self.lbl_captured_white.config(text="".join(self.white_captured))

        # Thinking badge
        if self.ai_working:
            self.thinking_badge.config(text="Computer is thinking…")
            self.thinking_badge.place(relx=0.5, rely=0.02, anchor="n")
        else:
            self.thinking_badge.place_forget()

    def _draw_coords_labels(self, sq, start_x, start_y):
        files = "abcdefgh"
        ranks = "87654321"
        for i, f in enumerate(files):
            x = start_x + i * sq + sq - 3
            y = start_y + self.BOARD_SIZE * sq + 2
            self.canvas.create_text(x, y, text=f, anchor="ne", font=("Arial", max(8, int(sq*0.18))), fill="#444")
        for i, r in enumerate(ranks):
            x = start_x - 2
            y = start_y + i * sq + 12
            self.canvas.create_text(x, y, text=r, anchor="ne", font=("Arial", max(8, int(sq*0.18))), fill="#444")

    def _square_rect(self, square, sq):
        file_idx = chess.square_file(square)
        rank_idx = chess.square_rank(square)
        row = 7 - rank_idx
        col = file_idx
        start_x, start_y = self._origin
        x0 = start_x + col * sq
        y0 = start_y + row * sq
        return (x0, y0, x0 + sq, y0 + sq)

    def _pixel_to_square(self, x, y):
        start_x, start_y = self._origin
        sq = self._current_square_px
        bx0, by0 = start_x, start_y
        bx1, by1 = start_x + self.BOARD_SIZE * sq, start_y + self.BOARD_SIZE * sq
        if not (bx0 <= x <= bx1 and by0 <= y <= by1):
            return None
        col = int((x - start_x) // sq)
        row = int((y - start_y) // sq)
        rank_idx = 7 - row
        file_idx = col
        return chess.square(file_idx, rank_idx)

    # ---------- Interaction ----------
    def on_canvas_click(self, event):
        # Ignore clicks while AI is thinking or if it's Black's turn
        if self.ai_working or self.board.turn == chess.BLACK:
            return

        sq = self._pixel_to_square(event.x, event.y)
        if sq is None:
            self.selected_sq = None
            self.legal_dests_for_selected = set()
            self.redraw()
            return

        piece = self.board.piece_at(sq)

        if self.selected_sq is None:
            if piece is not None and piece.color == self.board.turn:
                self.selected_sq = sq
                self.legal_dests_for_selected = {
                    mv.to_square for mv in self.board.legal_moves if mv.from_square == sq
                }
            self.redraw()
            return

        if sq == self.selected_sq:
            self.selected_sq = None
            self.legal_dests_for_selected = set()
            self.redraw()
            return

        if sq in self.legal_dests_for_selected:
            self.try_move(self.selected_sq, sq)  # human move
            return

        if piece is not None and piece.color == self.board.turn:
            self.selected_sq = sq
            self.legal_dests_for_selected = {
                mv.to_square for mv in self.board.legal_moves if mv.from_square == sq
            }
            self.redraw()
            return

        self.selected_sq = None
        self.legal_dests_for_selected = set()
        self.redraw()

    def try_move(self, from_sq, to_sq):
        legal_moves = [m for m in self.board.legal_moves if m.from_square == from_sq and m.to_square == to_sq]
        if not legal_moves:
            self._flash_info("Illegal move")
            self.selected_sq = None
            self.legal_dests_for_selected = set()
            self.redraw()
            return

        move_to_play = None

        # Handle promotion prompt for human
        is_pawn_promo = (
            self.board.piece_at(from_sq) and
            self.board.piece_at(from_sq).piece_type == chess.PAWN and
            chess.square_rank(to_sq) in (0, 7)
        )
        if len(legal_moves) > 1 or is_pawn_promo:
            promo = self.ask_promotion(self.board.turn)
            if promo is None:
                return
            for mv in legal_moves:
                if mv.promotion == promo:
                    move_to_play = mv
                    break
            if move_to_play is None:
                move_to_play = chess.Move(from_sq, to_sq, promotion=promo)
        else:
            move_to_play = legal_moves[0]

        captured_char = self._capture_char_for_move(move_to_play)
        san_text = self.board.san(move_to_play)
        self.board.push(move_to_play)
        self.last_move = move_to_play

        if captured_char:
            # After push, if it's White to move, Black just moved; we want captured list per capturer
            if self.board.turn == chess.WHITE:
                self.white_captured.append(captured_char)  # white pieces captured by Black
            else:
                self.black_captured.append(captured_char)

        self.move_san_list.append(san_text)
        self._render_history()

        self.selected_sq = None
        self.legal_dests_for_selected = set()
        self.redraw()

        # End checks / trigger AI
        self.post_move_checks()
        self.maybe_trigger_ai()

    def _capture_char_for_move(self, move):
        if not self.board.is_capture(move):
            return ""
        captured_piece = self.board.piece_at(move.to_square)
        if captured_piece is None:
            if self.board.is_en_passant(move):
                if self.board.turn == chess.WHITE:
                    captured_sq = move.to_square - 8
                else:
                    captured_sq = move.to_square + 8
                captured_piece = self.board.piece_at(captured_sq)
        if captured_piece:
            return self.PIECES[(captured_piece.piece_type, captured_piece.color)]
        return ""

    def ask_promotion(self, white_to_move):
        win = tk.Toplevel(self.root)
        win.title("Choose promotion")
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text="Promote pawn to:", font=("Arial", 12, "bold")).pack(padx=12, pady=(12,6))
        choice = {"value": None}
        btns = tk.Frame(win)
        btns.pack(padx=12, pady=(0,12))
        for label, pt, san in self.PROMO_CHOICES:
            sym = self.PIECES[(pt, white_to_move)]
            def make_cmd(val=pt):
                return lambda: (choice.update(value=val), win.destroy())
            tk.Button(btns, text=f"{sym}  {label}", width=14, command=make_cmd()).grid(sticky="ew", pady=3)
        tk.Button(win, text="Cancel", command=win.destroy).pack(pady=(0,10))
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + self.root.winfo_width()//2 - 100
        y = self.root.winfo_rooty() + self.root.winfo_height()//2 - 80
        win.geometry(f"+{x}+{y}")
        win.wait_window()
        return choice["value"]

    def _render_history(self):
        lines = []
        for idx in range(0, len(self.move_san_list), 2):
            move_no = idx // 2 + 1
            white_san = self.move_san_list[idx]
            black_san = self.move_san_list[idx+1] if idx+1 < len(self.move_san_list) else ""
            lines.append(f"{move_no:>2}. {white_san:<8} {black_san}")
        text = "\n".join(lines)
        self.history.configure(state="normal")
        self.history.delete("1.0", "end")
        self.history.insert("1.0", text)
        self.history.configure(state="disabled")
        self.history.see("end")

    # ---------- File I/O ----------
    def save_pgn(self):
        if len(self.board.move_stack) == 0:
            messagebox.showinfo("Save PGN", "No moves to save yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Save PGN", defaultextension=".pgn",
            filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")]
        )
        if not path: return
        game = chess.pgn.Game()
        game.headers["Event"] = "Casual Game"
        game.headers["Site"] = "Tk Chess"
        game.headers["White"] = "You"
        game.headers["Black"] = "Computer"
        node = game
        temp = chess.Board()
        for mv in self.board.move_stack:
            node = node.add_variation(mv)
            temp.push(mv)
        game.headers["Result"] = self.board.result() if self.board.is_game_over() else "*"
        with open(path, "w", encoding="utf-8") as f:
            print(game, file=f)
        messagebox.showinfo("Save PGN", f"Saved to:\n{path}")

    def load_pgn(self):
        path = filedialog.askopenfilename(
            title="Load PGN",
            filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")]
        )
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                game = chess.pgn.read_game(f)
            if game is None:
                messagebox.showerror("Load PGN", "Could not read a PGN game.")
                return
            self.board = chess.Board()
            self.white_captured.clear()
            self.black_captured.clear()
            self.move_san_list.clear()
            self.last_move = None
            self.selected_sq = None
            self.legal_dests_for_selected = set()
            node = game
            while node.variations:
                node = node.variations[0]
                mv = node.move
                captured_char = self._capture_char_for_move(mv)
                san_text = self.board.san(mv)
                self.board.push(mv)
                self.last_move = mv
                if captured_char:
                    if self.board.turn == chess.WHITE:
                        self.white_captured.append(captured_char)
                    else:
                        self.black_captured.append(captured_char)
                self.move_san_list.append(san_text)
            self._render_history()
            self.redraw()
            messagebox.showinfo("Load PGN", "PGN loaded.")
            self.maybe_trigger_ai()
        except Exception as e:
            messagebox.showerror("Load PGN", f"Failed to load PGN:\n{e}")

    # ---------- Game Flow ----------
    def restart(self):
        if messagebox.askyesno("Restart Game", "Start a new game vs the computer?"):
            self.board = chess.Board()
            self.selected_sq = None
            self.legal_dests_for_selected = set()
            self.last_move = None
            self.white_captured.clear()
            self.black_captured.clear()
            self.move_san_list.clear()
            self._render_history()
            self.redraw()
            self.maybe_trigger_ai()

    def post_move_checks(self):
        if self.board.is_checkmate():
            winner = "White" if not self.board.turn else "Black"
            messagebox.showinfo("Checkmate", f"Checkmate!\n{winner} wins.")
        elif self.board.is_stalemate():
            messagebox.showinfo("Stalemate", "Stalemate.\nDrawn game.")
        elif self.board.is_insufficient_material():
            messagebox.showinfo("Draw", "Draw by insufficient material.")
        elif self.board.can_claim_threefold_repetition():
            messagebox.showinfo("Draw", "Draw by threefold repetition (claimable).")
        elif self.board.is_check():
            side = "White" if self.board.turn == chess.WHITE else "Black"
            messagebox.showinfo("Check", f"{side} is in check!")

    def maybe_trigger_ai(self):
        """If it's Black's turn and game not over, let the computer move."""
        if self.board.turn == chess.BLACK and not self.board.is_game_over():
            if not self.ai_working:
                self.ai_working = True
                self.redraw()
                self.ai_thread = threading.Thread(target=self._compute_and_play_ai, daemon=True)
                self.ai_thread.start()

    def _compute_and_play_ai(self):
        # Compute best move on a copy to avoid interfering with GUI
        depth = int(self.ai_depth.get())
        board_copy = self.board.copy()
        # Ensure promotions by AI default to queen (python-chess handles if m.promotion is None for non-pawn)
        best = find_best_move(board_copy, max(1, min(6, depth)))
        # Apply on main thread
        self.root.after(10, lambda: self._apply_ai_move(best))

    def _apply_ai_move(self, move: chess.Move):
        try:
            if move is None or move not in self.board.legal_moves:
                # Fallback random
                move = random.choice(list(self.board.legal_moves))
            captured_char = self._capture_char_for_move(move)
            san_text = self.board.san(move)
            self.board.push(move)
            self.last_move = move
            if captured_char:
                if self.board.turn == chess.WHITE:
                    self.white_captured.append(captured_char)
                else:
                    self.black_captured.append(captured_char)
            self.move_san_list.append(san_text)
            self._render_history()
            self.redraw()
            self.post_move_checks()
        finally:
            self.ai_working = False
            self.redraw()

    def _flash_info(self, text):
        lbl = tk.Label(self.root, text=text, bg="#333", fg="#fff", padx=10, pady=4)
        lbl.place(relx=0.5, rely=1.0, anchor="s")
        self.root.after(900, lbl.destroy)


def main():
    root = tk.Tk()
    try:
        root.tk.call('tk', 'scaling', 1.0)
    except Exception:
        pass
    app = ChessGUI(root)
    min_w = ChessGUI.SQUARE_PX * 8 + 320
    min_h = ChessGUI.SQUARE_PX * 8 + 80
    root.minsize(min_w, min_h)
    root.mainloop()

if __name__ == "__main__":
    main()
