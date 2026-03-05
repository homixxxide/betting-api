"""
ARM BET API Server для Railway
Автоматический деплой с постоянным URL
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
from datetime import datetime
import logging
import os

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# Путь к базе данных
DB_PATH = os.getenv('DATABASE_PATH', 'betting_bot.db')

def get_db():
    """Подключение к базе данных"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def calculate_odds(match_id, team_id):
    """Расчет коэффициентов"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT team_id, amount FROM bets WHERE match_id = ? AND status = 'active'", (match_id,))
    bets = c.fetchall()
    conn.close()
    
    if not bets:
        return 2.0
    
    total_amount = sum(bet['amount'] for bet in bets)
    team_amount = sum(bet['amount'] for bet in bets if bet['team_id'] == team_id)
    
    if team_amount == 0:
        return 3.0
    
    commission_multiplier = 0.85
    odds = (total_amount / team_amount) * commission_multiplier
    odds = max(1.1, min(5.0, odds))
    
    return round(odds, 2)

@app.route('/')
def index():
    """Главная страница"""
    return jsonify({
        'name': 'ARM BET API',
        'version': '1.0',
        'status': 'running',
        'endpoints': {
            'health': '/api/health',
            'matches': '/api/matches',
            'user': '/api/user/<id>',
            'leaderboard': '/api/leaderboard',
            'my_bets': '/api/my-bets/<id>'
        }
    })

@app.route('/api/health')
def health():
    """Проверка работоспособности"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'database': os.path.exists(DB_PATH)
    })

@app.route('/api/matches')
def get_matches():
    """Получить все матчи"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute("""
            SELECT 
                m.match_id,
                m.status,
                t1.team_id as team1_id,
                t1.name as team1_name,
                t1.emoji as team1_emoji,
                t2.team_id as team2_id,
                t2.name as team2_name,
                t2.emoji as team2_emoji
            FROM matches m
            JOIN teams t1 ON m.team1_id = t1.team_id
            JOIN teams t2 ON m.team2_id = t2.team_id
            WHERE m.status IN ('upcoming', 'live')
            ORDER BY m.created_at DESC
        """)
        
        matches = []
        for row in c.fetchall():
            match_id = row['match_id']
            
            odds1 = calculate_odds(match_id, row['team1_id'])
            odds2 = calculate_odds(match_id, row['team2_id'])
            
            c.execute("""
                SELECT team_id, SUM(amount) as total
                FROM bets
                WHERE match_id = ? AND status = 'active'
                GROUP BY team_id
            """, (match_id,))
            
            bet_totals = {r['team_id']: r['total'] for r in c.fetchall()}
            total_bets = sum(bet_totals.values())
            
            if total_bets > 0:
                team1_percent = int((bet_totals.get(row['team1_id'], 0) / total_bets) * 100)
                team2_percent = 100 - team1_percent
            else:
                team1_percent = 50
                team2_percent = 50
            
            matches.append({
                'match_id': match_id,
                'status': row['status'],
                'league': 'ARM BET Championship',
                'team1': {
                    'team_id': row['team1_id'],
                    'name': row['team1_name'],
                    'emoji': row['team1_emoji'] or ''
                },
                'team2': {
                    'team_id': row['team2_id'],
                    'name': row['team2_name'],
                    'emoji': row['team2_emoji'] or ''
                },
                'odds1': odds1,
                'odds2': odds2,
                'bet_distribution': {
                    'team1': team1_percent,
                    'team2': team2_percent
                }
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'matches': matches,
            'count': len(matches)
        })
        
    except Exception as e:
        logging.error(f"Error getting matches: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/user/<int:user_id>')
def get_user(user_id):
    """Получить данные пользователя"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute("SELECT season_id FROM seasons WHERE is_active = 1 LIMIT 1")
        season = c.fetchone()
        
        if not season:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'No active season'
            }), 404
        
        season_id = season['season_id']
        
        c.execute("""
            SELECT current_balance, bets_count, total_won, total_lost
            FROM season_players
            WHERE user_id = ? AND season_id = ?
        """, (user_id, season_id))
        
        player = c.fetchone()
        
        if not player:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'User not found'
            }), 404
        
        conn.close()
        
        return jsonify({
            'success': True,
            'user': {
                'balance': player['current_balance'],
                'bets_count': player['bets_count'],
                'total_won': player['total_won'],
                'total_lost': player['total_lost']
            }
        })
        
    except Exception as e:
        logging.error(f"Error getting user: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/leaderboard')
def get_leaderboard():
    """Таблица лидеров"""
    try:
        limit = request.args.get('limit', 10, type=int)
        
        conn = get_db()
        c = conn.cursor()
        
        c.execute("SELECT season_id FROM seasons WHERE is_active = 1 LIMIT 1")
        season = c.fetchone()
        
        if not season:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'No active season'
            }), 404
        
        season_id = season['season_id']
        
        c.execute("""
            SELECT 
                u.username,
                sp.current_balance,
                sp.bets_count,
                sp.total_won
            FROM season_players sp
            JOIN users u ON sp.user_id = u.user_id
            WHERE sp.season_id = ?
            ORDER BY sp.current_balance DESC
            LIMIT ?
        """, (season_id, limit))
        
        leaders = []
        for idx, row in enumerate(c.fetchall(), 1):
            leaders.append({
                'rank': idx,
                'username': row['username'],
                'balance': row['current_balance'],
                'bets_count': row['bets_count'],
                'total_won': row['total_won']
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'leaderboard': leaders
        })
        
    except Exception as e:
        logging.error(f"Error getting leaderboard: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/my-bets/<int:user_id>')
def get_my_bets(user_id):
    """Ставки пользователя"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute("""
            SELECT 
                b.bet_id,
                b.match_id,
                b.amount,
                b.odds,
                b.status,
                b.created_at,
                t.name as team_name,
                t.emoji as team_emoji
            FROM bets b
            JOIN teams t ON b.team_id = t.team_id
            WHERE b.user_id = ?
            ORDER BY b.created_at DESC
            LIMIT 20
        """, (user_id,))
        
        bets = []
        for row in c.fetchall():
            bets.append({
                'bet_id': row['bet_id'],
                'match_id': row['match_id'],
                'amount': row['amount'],
                'odds': row['odds'],
                'status': row['status'],
                'team_name': row['team_name'],
                'team_emoji': row['team_emoji'] or '',
                'created_at': row['created_at']
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'bets': bets
        })
        
    except Exception as e:
        logging.error(f"Error getting bets: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    
    print("=" * 50)
    print("ARM BET API Server")
    print("=" * 50)
    print(f"Port: {port}")
    print(f"Database: {DB_PATH}")
    print("=" * 50)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )
