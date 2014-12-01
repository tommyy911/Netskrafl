﻿# -*- coding: utf-8 -*-

""" Web server for netskrafl.appspot.com

    Author: Vilhjalmur Thorsteinsson, 2014

    This web server module uses the Flask framework to implement
    a crossword game similar to SCRABBLE(tm).

    The actual game logic is found in skraflplayer.py and
    skraflmechanics.py. The web client code is found in netskrafl.js

    The server is compatible with Python 2.7 and 3.x, CPython and PyPy.
    (To get it to run under PyPy 2.7.6 the author had to patch
    \pypy\lib-python\2.7\mimetypes.py to fix a bug that was not
    present in the CPython 2.7 distribution of the same file.)

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

import logging
import time
import collections

from random import randint
from datetime import datetime

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, session, url_for

from google.appengine.api import users

from skraflmechanics import Manager, State, Board, Rack, Move, PassMove, ExchangeMove, ResignMove, Error
from skraflplayer import AutoPlayer
from languages import Alphabet
from skrafldb import Unique, UserModel, GameModel, MoveModel


# Standard Flask initialization

app = Flask(__name__)
app.config['DEBUG'] = False

# !!! TODO: Change this to read the secret key from a config file at run-time
app.secret_key = '\x03\\_,i\xfc\xaf=:L\xce\x9b\xc8z\xf8l\x000\x84\x11\xe1\xe6\xb4M'

manager = Manager()


class User:

    """ Information about a human user including nickname and preferences """

    def __init__(self):
        u = users.get_current_user()
        if u is None:
            self._user_id = None
        else:
            self._user_id = u.user_id()
        self._nickname = u.nickname() # Default
        self._inactive = False
        self._preferences = { }

    # The users that have been authenticated in this session
    _cache = dict()

    def fetch(self):
        u = UserModel.fetch(self._user_id)
        if u is None:
            UserModel.create(self._user_id, self.nickname())
            # Use the default properties for a newly created user
            return
        self._nickname = u.nickname
        self._inactive = u.inactive
        self._preferences = u.prefs

    def update(self):
        UserModel.update(self._user_id, self._nickname, self._inactive, self._preferences)

    def id(self):
        return self._user_id

    def nickname(self):
        return self._nickname or self._user_id

    def set_nickname(self, nickname):
        self._nickname = nickname

    def logout_url(self):
        return users.create_logout_url("/")

    @classmethod
    def current(cls):
        """ Return the currently logged in user """
        user = users.get_current_user()
        if user is None:
            return None
        if user.user_id() in User._cache:
            return User._cache[user.user_id()]
        u = cls()
        u.fetch()
        User._cache[u.id()] = u
        return u

    @classmethod
    def current_nickname(cls):
        """ Return the nickname of the current user """
        u = cls.current()
        if u is None:
            return None
        return u.nickname()


class LRUCache:

    """ A simple LRU cache structure to store games in memory """

    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = collections.OrderedDict()

    def get(self, key):
        try:
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        except KeyError:
            return None

    def set(self, key, value):
        try:
            self.cache.pop(key)
        except KeyError:
            if len(self.cache) >= self.capacity:
                self.cache.popitem(last = False)
        self.cache[key] = value

    def delete(self, key):
        try:
            self.cache.pop(key)
        except KeyError:
            pass


class Game:

    """ A wrapper class for a particular game that is in process
        or completed. Contains inter alia a State instance.
    """

    # The human-readable name of the computer player
    AUTOPLAYER_LEVEL_3 = u"Fullsterkur"
    AUTOPLAYER_STRENGTH_3 = 0 # Always picks best move
    AUTOPLAYER_LEVEL_2 = u"Miðlungur"
    AUTOPLAYER_STRENGTH_2 = 8 # Picks one of the eight best moves
    AUTOPLAYER_LEVEL_1 = u"Amlóði"
    AUTOPLAYER_STRENGTH_1 = 15 # Picks one of the fifteen best moves

    UNDEFINED_NAME = u"[Ónefndur]"

    def __init__(self, uuid = None):
        # Unique id of the game
        self.uuid = uuid
        # The start time of the game
        self.timestamp = None
        # The nickname of the human (local) player
        self.username = None
        # The current game state
        self.state = None
        # Is the human player 0 or 1, where player 0 begins the game?
        self.player_index = 0
        # The ability level of the autoplayer (0 = strongest)
        self.robot_level = 0
        # The last move made by the autoplayer
        self.last_move = None
        # Was the game finished by resigning?
        self.resigned = False
        # History of moves in this game so far, in tuples: (player, move, rack)
        self.moves = []
        # Initial rack contents
        self.initial_racks = [None, None]

    # The current game state held in memory for different users
    # A capacity of 200 seemed to cause occasional out-of-memory errors in
    # Google App Engine; trying 100
    _cache = LRUCache(capacity = 100)

    def _make_new(self, username, robot_level):
        """ Initialize a new, fresh game """
        self.username = username
        self.state = State(drawtiles = True)
        self.initial_racks[0] = self.state.rack(0)
        self.initial_racks[1] = self.state.rack(1)
        self.robot_level = robot_level
        self.player_index = randint(0, 1)
        self.timestamp = datetime.utcnow()
        self.set_human_name(username)

    @classmethod
    def current(cls):
        """ Obtain the current game state """
        user = User.current()
        user_id = None if user is None else user.id()
        if not user_id:
            # No game state found
            return None
        # First check the cache to see if we have the game already in memory
        game = Game._cache.get(user_id)
        if not game is None:
            return game
        # No game in cache: attempt to find one in the database
        uuid = GameModel.find_live_game(user_id)
        if uuid is None:
            # Not found in persistent storage
            return None
        # Load from persistent storage
        return cls.load(uuid, user.nickname())

    @classmethod
    def new(cls, username, robot_level):
        """ Start and initialize a new game """
        game = cls(Unique.id()) # Assign a new unique id to the game
        game._make_new(username, robot_level)
        # Cache the game so it can be looked up by user id
        user = User.current()
        if user is not None:
            Game._cache.set(user.id(), game)
        # If AutoPlayer is first to move, generate the first move
        if game.player_index == 1:
            game.autoplayer_move()
        # Store the new game in persistent storage
        game.store()
        return game

    @classmethod
    def load(cls, uuid, username):

        """ Load an already existing game from persistent storage """

        gm = GameModel.fetch(uuid)
        if gm is None:
            # A game with this uuid is not found in the database: give up
            return None

        # Initialize a new Game instance with a pre-existing uuid
        game = cls(uuid)

        game.username = username
        game.timestamp = gm.timestamp
        game.state = State(drawtiles = False)

        if gm.player0 is None:
            # Player 0 is an Autoplayer
            game.player_index = 1 # Human (local) player is 1
        else:
            assert gm.player1 is None
            game.player_index = 0 # Human (local) player is 0

        game.robot_level = gm.robot_level # Must come before set_human_name()
        game.set_human_name(username)

        # Load the initial racks
        game.initial_racks[0] = gm.irack0
        game.initial_racks[1] = gm.irack1

        # Load the current racks
        game.state.set_rack(0, gm.rack0)
        game.state.set_rack(1, gm.rack1)

        # Process the moves
        player = 0
        for mm in gm.moves:

            m = None
            if mm.coord:

                # Normal tile move
                # Decode the coordinate: A15 = horizontal, 15A = vertical
                if mm.coord[0] in Board.ROWIDS:
                    row = Board.ROWIDS.index(mm.coord[0])
                    col = int(mm.coord[1:]) - 1
                    horiz = True
                else:
                    row = Board.ROWIDS.index(mm.coord[-1])
                    col = int(mm.coord[0:-1]) - 1
                    horiz = False
                # The tiles string may contain wildcards followed by their meaning
                # Remove the ? marks to get the "plain" word formed
                if mm.tiles is not None:
                    m = Move(mm.tiles.replace(u'?', u''), row, col, horiz)
                    m.make_covers(game.state.board(), mm.tiles)

            elif mm.tiles[0:4] == u"EXCH":

                # Exchange move
                m = ExchangeMove(mm.tiles[5:])

            elif mm.tiles == u"PASS":

                # Pass move
                m = PassMove()

            elif mm.tiles == u"RSGN":

                # Game resigned
                m = ResignMove(- mm.score)

            assert m is not None
            if m:
                # Do a "shallow apply" of the move, which updates
                # the board and internal state variables but does
                # not modify the bag or the racks
                game.state.apply_move(m, True)
                # Append to the move history
                game.moves.append((player, m, mm.rack))
                player = 1 - player

        # If the moves were correctly applied, the scores should match
        assert game.state._scores[0] == gm.score0
        assert game.state._scores[1] == gm.score1

        # Find out what tiles are now in the bag
        game.state.recalc_bag()

        # Cache the game so it can be looked up by user id
        user = User.current()
        if user is not None:
            Game._cache.set(user.id(), game)
        return game

    def store(self):
        """ Store the game state in persistent storage """
        assert self.uuid is not None
        user = User.current()
        if user is None:
            # No current user: can't store game
            assert False
            return
        gm = GameModel(id = self.uuid)
        gm.set_player(self.player_index, user.id())
        gm.set_player(1 - self.player_index, None)
        gm.irack0 = self.initial_racks[0]
        gm.irack1 = self.initial_racks[1]
        gm.rack0 = self.state.rack(0)
        gm.rack1 = self.state.rack(1)
        gm.score0 = self.state.scores()[0]
        gm.score1 = self.state.scores()[1]
        gm.to_move = len(self.moves) % 2
        gm.robot_level = self.robot_level
        gm.over = self.state.is_game_over()
        movelist = []
        for player, m, rack in self.moves:
            mm = MoveModel()
            coord, tiles, score = m.summary(self.state.board())
            mm.coord = coord
            mm.tiles = tiles
            mm.score = score
            mm.rack = rack
            movelist.append(mm)
        gm.moves = movelist
        gm.put()

    def id(self):
        """ Returns the unique id of this game """
        return self.uuid

    def set_human_name(self, nickname):
        """ Set the nickname of the human player """
        if nickname[0:8] == u"https://":
            # Raw name (path) from Google Accounts: use a more readable version
            nickname = Game.UNDEFINED_NAME
        self.state.set_player_name(self.player_index, nickname)
        # Set the autoplayer's name as well
        ap_name = Game.AUTOPLAYER_LEVEL_3 # Strongest player by default
        if self.robot_level >= Game.AUTOPLAYER_STRENGTH_1:
            ap_name = Game.AUTOPLAYER_LEVEL_1 # Weakest player
        elif self.robot_level >= Game.AUTOPLAYER_STRENGTH_2:
            ap_name = Game.AUTOPLAYER_LEVEL_2 # Middle player
        self.state.set_player_name(1 - self.player_index, ap_name)

    def resign(self):
        """ The human player is resigning the game """
        self.resigned = True

    def is_over(self):
        """ Return True if the game is over """
        return self.state.is_game_over()

    def allows_best_moves(self):
        """ Returns True if this game supports full review (has stored racks, etc.) """
        if self.initial_racks[0] is None or self.initial_racks[1] is None:
            # This is an old game stored without rack information: can't display best moves
            return False
        # !!! TBD: add the following check
        #if not self.is_over():
        #    # Never show best moves for games that are still being played
        #    return False
        return True

    def autoplayer_move(self):
        """ Let the AutoPlayer make its move """
        # !!! DEBUG for testing various move types
        # rnd = randint(0,3)
        # if rnd == 0:
        #     print(u"Generating ExchangeMove")
        #     move = ExchangeMove(self.state.player_rack().contents()[0:randint(1,7)])
        # else:
        apl = AutoPlayer(self.state, self.robot_level)
        move = apl.generate_move()
        self.state.apply_move(move)
        self.moves.append((1 - self.player_index, move, self.state.rack(1 - self.player_index)))
        self.last_move = move

    def human_move(self, move):
        """ Register the human move, update the score and move list """
        self.state.apply_move(move)
        self.moves.append((self.player_index, move, self.state.rack(self.player_index)))
        self.last_move = None # No autoplayer move yet

    def enum_tiles(self, state = None):
        """ Enumerate all tiles on the board in a convenient form """
        if state is None:
            state = self.state
        for x, y, tile, letter in state.board().enum_tiles():
            yield (Board.ROWIDS[x] + str(y + 1), tile, letter,
                0 if tile == u'?' else Alphabet.scores[tile])

    def state_after_move(self, move_number):
        """ Return a game state after the indicated move, 0=beginning state """
        s = State(drawtiles = False)
        for ix in range(2):
            s.set_player_name(ix, self.state.player_name(ix))
            if self.initial_racks[ix] is None:
                # Load the current rack rather than nothing
                s.set_rack(ix, self.state.rack(ix))
            else:
                # Load the initial rack
                s.set_rack(ix, self.initial_racks[ix])
            logging.info(u"Setting rack {0} to '{1}'".format(ix, s.rack(ix)).encode("latin-1"))
        # Apply the moves
        for player, m, rack in self.moves[0 : move_number]:
            s.apply_move(m, True)
            if rack is not None:
                s.set_rack(player, rack)
        s.recalc_bag()
        return s

    BAG_SORT_ORDER = Alphabet.order + u'?'

    def display_bag(self):
        """ Returns the bag as it should be displayed, i.e. including the autoplayer's rack """
        displaybag = self.state.display_bag(1 - self.player_index)
        return u''.join(sorted(displaybag, key=lambda ch: Game.BAG_SORT_ORDER.index(ch)))

    def num_moves(self):
        """ Returns the number of moves in the game so far """
        return len(self.moves)

    def client_state(self):
        """ Create a package of information for the client about the current state """
        reply = dict()
        if self.state.is_game_over():
            # The game is now over - one of the players finished it
            reply["result"] = Error.GAME_OVER # Not really an error
            num_moves = 1
            if self.last_move is not None:
                # Show the autoplayer move if it was the last move in the game
                reply["lastmove"] = self.last_move.details()
                num_moves = 2 # One new move to be added to move list
            newmoves = [(player, m.summary(self.state.board())) for player, m, rack in self.moves[-num_moves:]]
            # Lastplayer is the player who finished the game
            lastplayer = self.moves[-1][0]
            if not self.resigned:
                # If the game did not end by resignation,
                # account for the losing rack
                rack = self.state.rack(1 - lastplayer)
                # Subtract the score of the losing rack from the losing player
                newmoves.append((1 - lastplayer, (u"", rack, -1 * Alphabet.score(rack))))
                # Add the score of the losing rack to the winning player
                newmoves.append((lastplayer, (u"", rack, 1 * Alphabet.score(rack))))
            # Add a synthetic "game over" move
            newmoves.append((1 - lastplayer, (u"", u"OVER", 0)))
            reply["newmoves"] = newmoves
            reply["bag"] = "" # Bag is now empty, by definition
            reply["xchg"] = False # Exchange move not allowed
        else:
            # Game is still in progress
            reply["result"] = 0 # Indicate no error
            reply["rack"] = self.state.player_rack().details()
            reply["lastmove"] = self.last_move.details()
            reply["newmoves"] = [(player, m.summary(self.state.board())) for player, m, rack in self.moves[-2:]]
            reply["bag"] = self.display_bag()
            reply["xchg"] = self.state.is_exchange_allowed()
        reply["scores"] = self.state.scores()
        return reply


    def statistics(self):
        """ Return a set of statistics on the game to be displayed by the client """
        reply = dict()
        if self.state.is_game_over():
            reply["result"] = Error.GAME_OVER # Indicate that the game is over (not really an error)
        else:
            reply["result"] = 0 # Game still in progress
        reply["gamestart"] = self.timestamp.isoformat(' ')[0:19] if self.timestamp is not None else u""
        reply["scores"] = sc = self.state.scores()
        # Number of moves made
        reply["moves0"] = m0 = (len(self.moves) + 1) // 2 # Floor division
        reply["moves1"] = m1 = (len(self.moves) + 0) // 2 # Floor division
        ncovers = [(p, m.num_covers()) for p, m, r in self.moves]
        bingoes = [(p, nc == Rack.MAX_TILES) for p, nc in ncovers]
        # Number of bingoes
        reply["bingoes0"] = sum([1 if p == 0 and bingo else 0 for p, bingo in bingoes])
        reply["bingoes1"] = sum([1 if p == 1 and bingo else 0 for p, bingo in bingoes])
        # Number of tiles laid down
        reply["tiles0"] = t0 = sum([nc if p == 0 else 0 for p, nc in ncovers])
        reply["tiles1"] = t1 = sum([nc if p == 1 else 0 for p, nc in ncovers])
        blanks = [0, 0]
        letterscore = [0, 0]
        cleanscore = [0, 0]
        # Loop through the moves, collecting stats
        for p, m, r in self.moves:
            coord, wrd, msc = m.summary(self.state.board())
            if wrd != u'RSGN':
                # Don't include a resignation penalty in the clean score
                cleanscore[p] += msc
            if m.num_covers() == 0:
                # Exchange, pass or resign move
                continue
            for coord, tile, letter, score in m.details():
                if tile == u'?':
                    blanks[p] += 1
                letterscore[p] += score
        # Number of blanks laid down
        reply["blanks0"] = b0 = blanks[0]
        reply["blanks1"] = b1 = blanks[1]
        # Sum of straight letter scores
        reply["letterscore0"] = lsc0 = letterscore[0]
        reply["letterscore1"] = lsc1 = letterscore[1]
        # Calculate average straight score of tiles laid down (excluding blanks)
        reply["average0"] = (float(lsc0) / (t0 - b0)) if (t0 > b0) else 0.0
        reply["average1"] = (float(lsc1) / (t1 - b1)) if (t1 > b1) else 0.0
        # Calculate point multiple of tiles laid down (score / nominal points)
        reply["multiple0"] = (float(cleanscore[0]) / lsc0) if (lsc0 > 0) else 0.0
        reply["multiple1"] = (float(cleanscore[1]) / lsc1) if (lsc1 > 0) else 0.0
        # Plain sum of move scores
        reply["cleantotal0"] = cleanscore[0]
        reply["cleantotal1"] = cleanscore[1]
        # Contribution of remaining tiles at the end of the game
        reply["remaining0"] = sc[0] - cleanscore[0]
        reply["remaining1"] = sc[1] - cleanscore[1]
        # Score ratios (percentages)
        totalsc = sc[0] + sc[1]
        reply["ratio0"] = (float(sc[0]) / totalsc * 100.0) if totalsc > 0 else 0.0
        reply["ratio1"] = (float(sc[1]) / totalsc * 100.0) if totalsc > 0 else 0.0
        return reply


def _process_move(movecount, movelist):
    """ Process a move from the client (the human player)
        Returns True if OK or False if the move was illegal
    """

    game = Game.current()

    if game is None:
        return jsonify(result = Error.LOGIN_REQUIRED)

    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result = Error.OUT_OF_SYNC)

    # Parse the move from the movestring we got back
    m = Move(u'', 0, 0)
    try:
        for mstr in movelist:
            if mstr == u"pass":
                # Pass move
                m = PassMove()
                break
            if mstr[0:5] == u"exch=":
                # Exchange move
                m = ExchangeMove(mstr[5:])
                break
            if mstr == u"rsgn":
                # Resign from game, forfeiting all points
                m = ResignMove(game.state.scores()[game.player_index])
                game.resign()
                break
            sq, tile = mstr.split(u'=')
            row = u"ABCDEFGHIJKLMNO".index(sq[0])
            col = int(sq[1:]) - 1
            if tile[0] == u'?':
                # If the blank tile is played, the next character contains
                # its meaning, i.e. the letter it stands for
                letter = tile[1]
                tile = tile[0]
            else:
                letter = tile
            # print(u"Cover: row {0} col {1}".format(row, col))
            m.add_cover(row, col, tile, letter)
    except Exception as e:
        logging.info(u"Exception in _process_move(): {0}".format(e).encode("latin-1"))
        m = None

    # Process the move string here
    # Unpack the error code and message
    err = game.state.check_legality(m)
    msg = ""
    if isinstance(err, tuple):
        err, msg = err

    if err != Error.LEGAL:
        # Something was wrong with the move:
        # show the user a corresponding error message
        return jsonify(result = err, msg = msg)

    # Move is OK: register it and update the state
    game.human_move(m)

    # Respond immediately with an autoplayer move
    # (can be a bit time consuming if rack has one or two blank tiles)
    if not game.state.is_game_over():
        game.autoplayer_move()

    if game.state.is_game_over():
        # If the game is now over, tally the final score
        game.state.finalize_score()

    # Make sure the new game state is persistently recorded
    game.store()

    # Return a state update to the client (board, rack, score, movelist, etc.)
    return jsonify(game.client_state())


@app.route("/submitmove", methods=['POST'])
def submitmove():
    """ Handle a move that is being submitted from the client """
    movelist = []
    movecount = 0
    if request.method == 'POST':
        # This URL should only receive Ajax POSTs from the client
        try:
            movelist = request.form.getlist('moves[]')
            movecount = int(request.form.get('mcount', 0))
        except:
            pass
    # Process the movestring
    return _process_move(movecount, movelist)


@app.route("/gamestats", methods=['POST'])
def gamestats():
    """ Calculate and return statistics on the current game """

    user = User.current()
    user_id = None if user is None else user.id()
    if not user_id:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    uuid = request.form.get('game', None)
    if uuid is None:
        game = Game.current()
    else:
        game = Game.load(uuid, user.nickname())

    if game is None:
        # !!! Debug
        # No live game found: attempt to find one in the database
        uuid = GameModel.find_finished_game(user_id)
        if uuid is not None:
            game = Game.load(uuid, user.nickname())

    if game is None:
       return jsonify(result = Error.LOGIN_REQUIRED)

    return jsonify(game.statistics())


@app.route("/review")
def review():
    """ Show game review page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url(url_for("review")))

    game = None
    uuid = request.args.get("game", None)

    if uuid is not None:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid, user.nickname())

    if game is None:
        game = Game.current()

    if game is None:
        # !!! Debug: load a finished game to display
        user_id = user.id()
        if not user_id:
            # No game state found
            return redirect(url_for("main"))
        # No game in cache: attempt to find one in the database
        uuid = GameModel.find_finished_game(user_id)
        if uuid is None:
            # Not found in persistent storage
            return redirect(url_for("main"))
        # Load from persistent storage
        game = Game.load(uuid, user.nickname())

    if game is None:
       return redirect(url_for("main"))

    move_number = int(request.args.get("move", "0"))
    state = game.state_after_move(move_number if move_number == 0 else move_number - 1)
    best_moves = None
    if game.allows_best_moves():
        apl = AutoPlayer(state)
        best_moves = apl.generate_best_moves(20)

    return render_template("review.html",
        user = user, game = game, state = state, move_number = move_number,
        best_moves = best_moves)


@app.route("/userprefs", methods=['GET', 'POST'])
def userprefs():
    """ Handler for the user preferences page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url(url_for("userprefs")))

    if request.method == 'POST':
        try:
            # Funny string addition below ensures that username is
            # a Unicode string under both Python 2 and 3
            nickname = u'' + request.form['nickname'].strip()
        except:
            nickname = u''
        if nickname:
            user.set_nickname(nickname)
            user.update()
            game = Game.current()
            if game is not None:
                game.set_human_name(nickname)
            return redirect(url_for("main"))
    return render_template("userprefs.html", user = user)


@app.route("/login", methods=['GET', 'POST'])
def login():
    """ Handler for the user login page """
    login_error = False
    if request.method == 'POST':
        try:
            # Funny string addition below ensures that username is
            # a Unicode string under both Python 2 and 3
            username = u'' + request.form['username'].strip()
        except:
            username = u''
        if username:
            # !!! TODO: Add validation of username here
            session['username'] = username
            return redirect(url_for("main"))
        login_error = True
    return render_template("login.html", err = login_error)


@app.route("/newgame", methods=['GET', 'POST'])
def newgame():
    """ Show page to initiate a new game """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url("/"))

    game = Game.current()
    if game is not None and not game.state.is_game_over():
        # The previous game is not over: can't create a new one
        return redirect(url_for("main"))

    if request.method == 'POST':
        # Initiate a new game against the selected opponent
        robot_level = 0
        if request.form['radio'] == "level3":
            # Full strength player
            robot_level = Game.AUTOPLAYER_STRENGTH_3
        elif request.form['radio'] == "level2":
            # Medium strength player (picks one out of best 5 moves at random)
            robot_level = Game.AUTOPLAYER_STRENGTH_2
        elif request.form['radio'] == "level1":
            # Low strength player (picks one out of 10 best moves at random)
            robot_level = Game.AUTOPLAYER_STRENGTH_1
        game = Game.new(user.nickname(), robot_level)
        return redirect(url_for("main"))

    return render_template("newgame.html", user = user)


@app.route("/logout")
def logout():
    """ Handler for the user logout page """
    session.pop('username', None)
    return redirect(url_for("login"))


@app.route("/")
def main():
    """ Handler for the main (index) page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url("/"))

    game = Game.current()
    if game is not None and game.state.is_game_over():
        # Trigger creation of a new game if the previous one was finished
        game = None

    if game is None:
        # Initiate a new game
        return redirect(url_for("newgame"))

    return render_template("board.html", game = game, user = user)


@app.route("/help")
def help():
    """ Show help page """
    return render_template("nshelp.html")


@app.route("/twoletter")
def twoletter():
    """ Show list of two letter words """
    return render_template("twoletter.html")


@app.errorhandler(404)
def page_not_found(e):
    """ Return a custom 404 error """
    return u'Sorry, nothing at this URL', 404


@app.errorhandler(500)
def server_error(e):
    """ Return a custom 500 error """
    return u'Sorry, unexpected error: {}'.format(e), 500


# Run a default Flask web server for testing if invoked directly as a main program

if __name__ == "__main__":
    app.run(debug=True)
