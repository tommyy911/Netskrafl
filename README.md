## Netskrafl - an Icelandic crossword game website

[![Join the chat at https://gitter.im/Netskrafl/Lobby](https://badges.gitter.im/Netskrafl/Lobby.svg)](https://gitter.im/Netskrafl/Lobby?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

### English summary

This repository contains the implementation of an Icelandic crossword game
inspired by SCRABBLE(tm).
The game, which is free-to-play, is accessible on the web at [https://netskrafl.is](https://netskrafl.is) and
[https://netskrafl.appspot.com](https://netskrafl.appspot.com)

![Screenshot from mobile UI](/resources/ScreencapMobile.PNG?raw=true "Screenshot from mobile UI")

The game backend is implemented in Python 2.7 for Google App Engine but the core code is also
compatible with Python 3.x and PyPy.

The frontend is a tablet- and smartphone-friendly web client in HTML5 and JavaScript connecting
via Ajax to a Flask-based web server on the backend.

The game contains a robot crossword player written in Python. The algorithm is based
on Appel & Jacobson's classic paper
["The World's Fastest Scrabble Program"](http://www.cs.cmu.edu/afs/cs/academic/class/15451-s06/www/lectures/scrabble.pdf).
At maximum strength level, the robot always plays the highest-scoring move possible but additional and
alternative strategies can be plugged in relatively easily. At the lowest strength level, the
robot is limited to a set of common words, about a quarter of the size of the entire word database.

The software has a range of features such as immediate tile-by-tile feedback on word validity and score,
real-time synchronized games with clocks, Elo scoring of players, an online chat window,
and the ability to view player track records.

The game uses a word database encoded in a Directed Acyclic Word Graph (DAWG).
For Icelandic, the graph contains almost 2.3 million word forms. Further information
about the DAWG implementation can be found in README.md in the
[Skrafl repository](https://github.com/vthorsteinsson/Skrafl) on GitHub.

The game mechanics are mostly found in ```skraflmechanics.py```.

The robot player is implemented in ```skraflplayer.py```.

The DAWG navigation code is in ```dawgdictionary.py```.

Particulars to the Icelandic language are found in ```languages.py```.

The main Flask web server is in ```netskrafl.py```.

The Game and User classes are found in ```skraflgame.py```.

The persistence layer, using the schemaless App Engine NDB database, is in ```skrafldb.py```.

The client JavaScript code is in ```static/netskrafl.js```.

The various Flask HTML templates are found in ```templates/*.html```.

The word database is in ```resources/ordalisti.text.dawg```.


### To build and run locally

#### Follow these steps:

0. Install [Python 2.7](https://www.python.org/downloads/release/python-2711/), possibly in a [virtualenv](https://pypi.python.org/pypi/virtualenv).

1. Download the [Google App Engine SDK](https://cloud.google.com/appengine/downloads) (GAE) for Python
and follow the installation instructions.

2. ```git clone https://github.com/mideind/Netskrafl``` to your GAE application directory.

3. Run ```pip install -t lib -r requirements.txt``` to install required Python packages so that they
are accessible to GAE.

4. Run ```python dawgbuilder.py``` to generate the DAWG ```*.pickle``` files. This takes a couple of minutes.

5. Create a secret session key for Flask in `resources/secret_key.bin` (see
[How to generate good secret keys](http://flask.pocoo.org/docs/0.10/quickstart/), you need to scroll down
to find the heading).

6. Install [Node.js](https://nodejs.org/en/download/) if you haven't already. Run ```npm install``` to install
Node dependencies.

7. In a separate terminal window, but in the Netskrafl directory, run ```grunt make```. Then run ```grunt```
to start watching changes of js and css files.

8. Run either ```runserver.bat``` or ```runserver.sh```.

#### Or, alternatively:

Run ```./setup-dev.sh``` (tested on Debian based Linux and OS X).


### Generating a new vocabulary file

To generate a new vocabulary file (```ordalistimax15.sorted.txt```), assuming you already
have the BÍN database in PostgreSQL (here in table ```ord19``` - remember to use the
```is_IS``` collation locale!), invoke ```psql```, log in to your database and
create the following view:

```sql
create or replace view skrafl as
   select stofn, utg, ordfl, fl, ordmynd, beyging from ord19
   where ordmynd ~ '^[aábdðeéfghiíjklmnoóprstuúvxyýþæö]{3,15}$'
   and fl <> 'bibl'
   and not ((beyging like 'SP-%-FT') or (beyging like 'SP-%-FT2'))
   order by ordmynd;
```

To explain, this extracts all 3-15 letter word forms containing only Icelandic lowercase
alphabetic characters, omitting the *bibl* (Biblical) category (which contains mostly
obscure proper names and derivations thereof), and also omitting plural question
forms (*spurnarmyndir í fleirtölu*).

Then, to generate the vocabulary file from the ```psql``` command line:

```sql
\copy (select distinct ordmynd from skrafl) to '/home/username/github/Netskrafl/resources/ordalistimax15.sorted.txt';
```


### Original Author
Vilhjálmur Þorsteinsson, Reykjavík, Iceland.

Contact me via GitHub for queries or information regarding Netskrafl.

Please contact me if you have plans for using Netskrafl as a basis for your
own game website and prefer not to operate under the conditions of the GNU GPL v3
license (see below).

### License

*Netskrafl - an Icelandic crossword game website*

*Copyright © 2020 Miðeind ehf.*

This set of programs is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This set of programs is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

The full text of the GNU General Public License is available here:
[http://www.gnu.org/licenses/gpl.html](http://www.gnu.org/licenses/gpl.html).

### Included third party software

Netskrafl contains the *DragDropTouch.js* module by Bernardo Castilho,
which is licensed under the MIT license as follows:

	Copyright © 2016 Bernardo Castilho

	Permission is hereby granted, free of charge, to any person obtaining a copy
	of this software and associated documentation files (the "Software"), to deal
	in the Software without restriction, including without limitation the rights
	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the Software is
	furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in all
	copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
	SOFTWARE.

Netskrafl contains the *jQuery UI Touch Punch* library by David Furfero, which
is licensed under the MIT license.

	Copyright © 2011 David Furfero

	The MIT license, as spelled out above, applies to this library.

### Trademarks

*SCRABBLE is a registered trademark. This software or its author are in no way affiliated
with or endorsed by the owners or licensees of the SCRABBLE trademark.*
