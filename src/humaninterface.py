import sys
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
import constants as c

import gui, dialog

#请注意，本程序仅为本地可视化调试工具，为不会使用或无法使用平台的用户提供帮助，未经过优化，内容非常丑陋，若想详细了解平台原理，请观看平台源代码
#pyqt is totally disastrous
#需要同时下载gui.py以及dialog.py
#以下基于plat.py和round_match.py

import constants as c  # 导入游戏常数
import time


# 平台


pos, dirt, phase, plat_cur, statelabel = None, None, None, None, None


class Platform:
    def __init__(self, states, match, livequeue, toSave, MAXTIME, ROUNDS):
        '''
        初始化
        -> 参数: states 保存先后手方模块元信息的字典
        -> 参数: match 比赛名称
        -> 参数: livequeue 直播通信队列
        -> 参数: toSave 是否保存为记录文件
        -> 参数: MAXTIME 最大时间限制
        -> 参数: ROUNDS 总回合数
        '''
        
        # 生成覆盖随机序列
        from random import randrange
        c.ARRAY = tuple(randrange(720720) for _ in range(ROUNDS))
        
        # 超时异常
        class Timeout(Exception):
            pass

        # 返回值
        class Result:
            def __init__(self, func):
                self.func = func
                self.result = Timeout()
            def call(self, *args, **kwargs):
                self.result = self.func(*args, **kwargs)
                
        # 超时退出的装饰器
        import threading
        def timeoutManager(maxtime, isFirst):
            def decorator(func):
                def wrappedFunc(*args, **kwargs):
                    result = Result(func)
                    thread = threading.Thread(target = result.call, args = (*args, ), kwargs = {**kwargs})
                    thread.setDaemon(True)
                    thread.start()
                    thread.join(maxtime - self.states[isFirst]['time'])
                    if isinstance(result.result, Timeout): self.states[isFirst]['time'] = maxtime
                    return result.result
                return wrappedFunc
            return decorator
        
        # 监测运行状态的装饰器
        import traceback
        def stateManager(isFirst):
            def decorator(func):
                @timeoutManager(MAXTIME * 1.1, isFirst)
                def wrappedFunc(*args, **kwargs):
                    try:
                        begin = time.perf_counter()
                        result = func(*args, **kwargs)
                        end = time.perf_counter()
                        self.states[isFirst]['time'] += end - begin
                    except:
                        result = None
                        self.states[isFirst]['error'] = True
                        self.states[isFirst]['exception'] = traceback.format_exc()
                    return result
                return wrappedFunc
            return decorator

        # 重载对象方法
        for isFirst in [True, False]:
            if states[isFirst]['player'] == 'human':
                continue
            states[isFirst]['player'].__init__ = stateManager(isFirst)(states[isFirst]['player'].__init__)
            states[isFirst]['player'].output = stateManager(isFirst)(states[isFirst]['player'].output)


        # 构建一个日志类, 可以实现直播功能
        class Log(list):
            def __init__(self, parent):
                list.__init__(self, [])
                self.parent = parent
                Log.add = Log._add if parent.livequeue != None else list.append

            def _add(self, log):
                self.append(log)
                self.parent.livequeue.put(self.parent)
                time.sleep(c.SLEEP)
                
        self.states = states                # 参赛AI运行状态
        self.match = match                  # 比赛名称
        self.livequeue = livequeue          # 直播工具
        self.toSave = toSave                # 保存记录文件
        self.maxtime = MAXTIME              # 最大时间限制
        self.rounds = ROUNDS                # 总回合数
        self.winner = None                  # 胜利者
        self.violator = None                # 违规者
        self.timeout = None                 # 超时者
        self.error = None                   # 报错者
        self.currentRound = 0               # 当前轮数
        self.change = False                 # 监控棋盘是否改变
        self.next = (None, None)            # 按照随机序列得到的下一个位置
        self.board = c.Chessboard(c.ARRAY)  # 棋盘
        self.log = Log(self)                # 日志, &d 决策 decision, &p 棋盘 platform, &e 事件 event

    def play(self):
        global match_object
        '''
        一局比赛, 返回player表现报告
        '''
        
        for isFirst in [True, False]:
            if self.states[isFirst]['player'] == 'human':
                continue
            self.states[isFirst]['player'].__init__(isFirst, c.ARRAY)
            
        # 检查双方是否合法加载
        if mode == 1:
            fail = [self.checkState(True), self.checkState(False)]
        else:
            fail = [0]
        if sum(fail) == 0:  # 双方合法加载
            self.match_object = self.start()
            try:
                _1 = next(self.match_object)
            except StopIteration:
                pass
        elif sum(fail) == 1:  # 一方合法加载
            self.winner = not fail[0]
        else:  # 双方非法加载
            if self.timeout == None:
                self.error = 'both'
            if self.error == None:
                self.timeout = 'both'

        self.save()  # 计分并保存
            
        return {True:  {'index': self.states[True]['index'],
                        'win': self.winner == True,
                        'lose': self.winner == False,
                        'violate': self.violator == True,
                        'timeout': self.timeout in [True, 'both'],
                        'error': self.error in [True, 'both'],
                        'time': self.states[True]['time'] - self.states[True]['time0'],
                        'exception': self.states[True]['exception']},
                False: {'index': self.states[False]['index'],
                        'win': self.winner == False,
                        'lose': self.winner == True,
                        'violate': self.violator == False,
                        'timeout': self.timeout in [False, 'both'],
                        'error': self.error in [False, 'both'],
                        'time': self.states[False]['time'] - self.states[False]['time0'],
                        'exception': self.states[False]['exception']},
                'name': self.name,
                'rounds': self.currentRound}
              
    def start(self):
        '''
        进行比赛
        '''

        def if_position(isFirst):
            return not (self.board.getNone(True) == [] and self.board.getNone(False) == [])

        def if_direction(isFirst):
            if self.board.getNone(isFirst) != []: return True  # 加快判定
            for _ in range(4):
                if self.board.copy().move(isFirst, _): return True
            return False
            
        def get_position(isFirst, currentRound):
            global pos
            self.next = self.board.getNext(isFirst, currentRound)  # 按照随机序列得到下一个位置
            if pos == None:
                self.board.updateTime(isFirst, self.maxtime - self.states[isFirst]['time'])  # 更新剩余时间
                position = self.states[isFirst]['player'].output(currentRound, self.board.copy(), 'position')  # 获取输出
                statelabel.setText(("player1" if isFirst else "player2") + " choose position " + str(position))
                if self.checkState(isFirst): return True  # 判断运行状态
                self.log.add('&d%d:%s set position %s' % (currentRound, c.PLAYERS[isFirst], str(position)))  # 记录
                if self.checkViolate(isFirst, 'position', position):
                    return True  # 判断是否违规
                else:
                    self.board.add(isFirst, position)  # 更新棋盘
                    self.log.add('&p%d:\n' % currentRound + self.board.__repr__())  # 记录
                    return False
            else:
                position = pos
                pos = None
                statelabel.setText(("player1" if isFirst else "player2") + " choose position " + str(position))
                if self.checkViolate(isFirst, 'position', position):
                    self.violator = None
                    return False
                else:
                    self.log.add('&d%d:%s set position %s' % (currentRound, c.PLAYERS[isFirst], str(position)))  # 记录
                    return True

        def get_direction(isFirst, currentRound):
            global dirt
            if dirt == None:
                self.board.updateTime(isFirst, self.maxtime - self.states[isFirst]['time'])  # 更新剩余时间
                direction = self.states[isFirst]['player'].output(currentRound, self.board.copy(), 'direction')  # 获取输出
                statelabel.setText(("player1" if isFirst else "player2") + " choose direction " + str(direction))
                if self.checkState(isFirst): return True  # 判断运行状态
                self.log.add('&d%d:%s set direction %s' % (currentRound, c.PLAYERS[isFirst], c.DIRECTIONS[direction]))  # 记录
                self.change = self.board.move(isFirst, direction)  # 更新棋盘
                if self.checkViolate(isFirst, 'direction', direction): return True  # 判断是否违规
                self.log.add('&p%d:\n' % currentRound + self.board.__repr__())  # 记录
                return False
            else:
                direction = dirt
                dirt = None
                statelabel.setText(("player1" if isFirst else "player2") + " choose direction " + str(direction))
                if self.checkViolate(isFirst, 'direction', direction):
                    self.violator = None
                    return False
                else:
                    self.log.add('&d%d:%s set direction %s' % (currentRound, c.PLAYERS[isFirst], c.DIRECTIONS[direction]))  # 记录
                    return True
                
        # 进行比赛
        global phase
        for _ in range(self.rounds):
            self.rnd = _
            phase = 0
            self.pf = True
            if if_position(True):
                if mode == 3 or mode == 4:
                    yield None
                else:
                    if get_position(True, _):
                        break
            print("yes")
            self.pf = False
            if if_position(False):
                if mode == 2 or mode == 4:
                    print("yes")
                    yield None
                else:
                    if get_position(False, _):
                        break
            phase = 1
            self.pf = True
            if if_direction(True):
                if mode == 3 or mode == 4:
                    yield None
                else:
                    if get_direction(True, _):
                        break
            self.pf = False
            if if_direction(False):
                if mode == 2 or mode == 4:
                    yield None
                else:
                    if get_direction(False, _):
                        break

        # 记录总轮数
        self.currentRound = _ + 1
        
        # 得到winner
        for _ in (self.timeout, self.violator, self.error):
            if _ != None:
                self.winner = not _
                self.log.add('&e:%s win' % (c.PLAYERS[self.winner]))
        #raise StopIteration
        
    def checkState(self, isFirst):
        '''
        检查是否超时和报错
        '''
        
        if self.states[isFirst]['time'] >= self.maxtime:  # 超时
            self.log.add('&e:%s time out' % (c.PLAYERS[isFirst]))
            self.timeout = isFirst
            return True
        if self.states[isFirst]['error']:  # 抛出异常
            self.log.add('&e:%s run time error' % (c.PLAYERS[isFirst]))
            self.error = isFirst
            return True
        return False

    def checkViolate(self, isFirst, mode, value):
        '''
        检查是否非法输出
        -> 违规有三种情形:
        -> 输出格式错误
        -> 选择的方格在可选范围之外
        -> 选择的方向使得合并前后棋盘没有变化
        '''
        
        if mode == 'position':
            if not (isinstance(value, tuple) and len(value) == 2 and value[0] in range(c.ROWS) and value[1] in range(c.COLUMNS)):
                self.log.add('&e:%s violate by illegal output of position' % (c.PLAYERS[isFirst]))
                self.violator = isFirst
                return True
            if self.board.getValue(value) == 0 and (self.board.getBelong(value) != isFirst or value == self.next):
                return False
            else:
                self.log.add('&e:%s violate by not achievable position' % (c.PLAYERS[isFirst]))
                self.violator = isFirst
                return True
        else:
            if value not in range(4):
                self.log.add('&e:%s violate by illegal output of direction' % (c.PLAYERS[isFirst]))
                self.violator = isFirst
                return True
            elif self.change:
                return False
            else:
                self.log.add('&e:%s violate by not achievable direction' % (c.PLAYERS[isFirst]))
                self.violator = isFirst
                return True
            self.change = False

    def save(self):
        '''
        计分并保存比赛记录
        '''
        
        # 获取所有棋子并计数
        results = {True: self.board.getScore(True), False: self.board.getScore(False)}
        scores = {True: {}, False: {}}
        for level in range(1, c.MAXLEVEL):
            scores[True][level] = results[True].count(level)
            scores[False][level] = results[False].count(level)

        # 比较比分
        if self.winner == None:
            for _ in reversed(range(1, c.MAXLEVEL)):
                self.log.add('&e:check level %d' % _)
                if scores[True][_] == scores[False][_]:
                    self.log.add('&e:level %d tied by %d' % (_, scores[True][_]))
                else:
                    self.winner = scores[True][_] > scores[False][_]
                    self.log.add('&e:%s win by level %d (%d to %d)' % (c.PLAYERS[self.winner], _, scores[True][_], scores[False][_]))
                    break
            else:
                self.log.add('&e:tied')

        # 保存对局信息, 可以用analyser.py解析
        self.name = repr(hash(time.perf_counter()))  # 对局名称
        if self.toSave:
            file = open('%s/%s.txt' % (self.match, self.name),'w')
            myDict = {True:'player 0', False:'player 1', None:'None', 'both':'both'}  # 协助转换为字符串
            title = 'player0: %d from path %s\n' % (self.states[True]['index'][0], self.states[True]['path']) + \
                    'player1: %d from path %s\n' % (self.states[False]['index'][0], self.states[False]['path']) + \
                    'time: %s\n' % time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()) + \
                    '{:*^45s}\n'.format('basic record')
            file.write(title)
            file.write('=' * 45 + '\n|{:^10s}|{:^10s}|{:^10s}|{:^10s}|\n'.format('timeout', 'violator', 'error', 'winner') + \
                       '-' * 45 + '\n|{:^10s}|{:^10s}|{:^10s}|{:^10s}|\n'.format(myDict[self.timeout], myDict[self.violator], myDict[self.error], myDict[self.winner]) + \
                       '=' * 45 + '\n')
            file.write('=' * 60 + '\n|%6s|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|\n' % ('player', *range(1, c.MAXLEVEL)) + \
                       '-' * 60 + '\n|%6d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|\n' % (0, *[scores[True][_] for _ in range(1, c.MAXLEVEL)]) + \
                       '-' * 60 + '\n|%6d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|%3d|\n' % (1, *[scores[False][_] for _ in range(1, c.MAXLEVEL)]) + \
                       '=' * 60 + '\n')
            file.flush()
            file.write('{:*^45s}\n'.format('complete record'))
            for log in self.log:
                file.write(log + '\n')  # '&'表示一条log的开始
                file.flush()
            file.close()
def main(playerList,
         savepath = None,
         livequeue = None,
         toSave = True,
         toReport = True,
         toGet = False,
         debug = False,
         REPEAT = c.REPEAT,
         MAXTIME = c.MAXTIME,
         ROUNDS = c.ROUNDS):
    '''
    主函数
    -> 参数: playerList 参赛队伍的模块列表, 支持绝对路径, 相对路径, 和已读取的类. 例如 playerList = ['player.py', 'player.py']
    -> 参数: savepath 比赛文件夹的保存路径, 支持相对路径, 支持函数返回值, 默认为在当前目录创建
    -> 参数: livequeue 直播进程通讯用的队列
    -> 参数: toSave 是否保存对局记录
    -> 参数: toReport 是否生成统计报告
    -> 参数: toGet 是否返回平台对象
    -> 参数: debug 是否打印报错信息
    -> 参数: REPEAT 单循环轮数
    -> 参数: MAXTIME 总时间限制
    -> 参数: ROUNDS 总回合数
    '''
    
    import time
    
    '''
    第一部分, 构建存放log文件的文件夹
    '''
    
    import os
    if callable(savepath): match = savepath()
    elif isinstance(savepath, str): match = savepath
    else: match = time.strftime('%Y-%m-%d %H-%M-%S', time.localtime())
    
    count = 0
    while True:  # 文件夹存在则创立副本
        count += 1
        try:
            _match = '_%d' % count if count != 1 else ''
            os.mkdir(match + _match)
            match += _match
            break
        except FileExistsError:
            continue

    '''
    第二部分, 导入模块并准备成绩记录
    '''
    
    # 导入全部ai模块
    global mode
    import sys
    Players = []
    time0 = [0 for count in range(len(playerList))]
    for count in range(len(playerList)):
        if playerList[count] == 'human':
            Players.append('human')
            continue
        if isinstance(playerList[count], tuple):  # 指定初始时间
            time0[count] = playerList[count][1]
            playerList[count] = playerList[count][0]
        if isinstance(playerList[count], str):  # 路径
            path = playerList[count]
            sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
            Players.append(__import__(os.path.splitext(os.path.basename(path))[0]).Player)
            sys.path.pop(0)
        else:  # 已读取的类
            Players.append(playerList[count])
    
    # 进行成绩记录的准备    
    matchResults = {'basic': [], 'exception': []}
    playerResults = [{True: {'win': [],
                             'lose': [],
                             'violate': [],
                             'timeout': [],
                             'error': [],
                             'time': []},
                      False: {'win': [],
                              'lose': [],
                              'violate': [],
                              'timeout': [],
                              'error': [],
                              'time': []},
                      'path': playerList[count]} for count in range(len(playerList))]
            
    def update(matchResults, playerResults, result):  # 更新成绩记录
        matchResults['basic'].append('name: %s -> player%d to player%d -> %d rounds'
                                    % (result['name'],
                                       result[True]['index'][0],
                                       result[False]['index'][0],
                                       result['rounds']))
        matchResults['exception'].append((result['name'], result[True]['exception'], result[False]['exception']))
        for isFirst in [True, False]:
            for _ in result[isFirst]:
                if _ not in  ['index', 'exception'] and result[isFirst][_]:
                    playerResults[result[isFirst]['index'][0]][isFirst][_].append(result['name'] if _ != 'time' else result[isFirst]['time'])
                    
    '''
    第三部分, 比赛
    '''
    
    # 开始游戏, 单循环先后手多次比赛
    kwargs = {'match': match,
              'livequeue': livequeue,
              'toSave': toSave,
              'MAXTIME': MAXTIME,
              'ROUNDS': ROUNDS}
    platforms = {}
    for count1 in range(len(playerList)):
        for count2 in range(count1 + 1, len(playerList)):
            platforms[(count1, count2)] = []
            platforms[(count2, count1)] = []
            for _ in range(REPEAT):
                for isFirst in [True, False]:
                    counts = (count1, count2) if isFirst else (count2, count1)
                    trueCount, falseCount = counts
                    platforms[counts].append(Platform({True: {'player': 'human' if Players[trueCount] == 'human' else object.__new__(Players[trueCount]),
                                                              'path': playerList[trueCount],
                                                              'time': time0[trueCount],
                                                              'time0': time0[trueCount],
                                                              'error': False,
                                                              'exception': None,
                                                              'index': (trueCount, True)},
                                                       False: {'player': 'human' if Players[falseCount] == 'human' else object.__new__(Players[falseCount]),
                                                               'path': playerList[falseCount],
                                                               'time': time0[falseCount],
                                                               'time0': time0[falseCount],
                                                               'error': False,
                                                               'exception': None,
                                                               'index': (falseCount, False)}}, **kwargs))
                    update(matchResults, playerResults, platforms[counts][-1].play())
                
    '''
    第四部分, 统计比赛结果
    '''
    
    # 统计全部比赛并归档到一个总文件中
    if toReport:
        f = open('%s/_.txt' % match, 'w')
        f.write('=' * 50 + '\n')
        f.write('total matches: %d\n' % len(matchResults['basic']))
        f.write('\n'.join(matchResults['basic']))
        f.write('\n' + '=' * 50 + '\n')
        f.flush()
        for count in range(len(playerList)):
            f.write('player%s from path %s\n\n' % (count, playerResults[count]['path']))
            player = playerResults[count][True]
            f.write('''offensive cases:
    average time: %.3f
        win rate: %.2f%%
        win: %d at
            %s
        lose: %d at
            %s
        violate: %d at
            %s
        timeout: %d at
            %s
        error: %d at
            %s
'''            %(sum(player['time']) / len(player['time']) if player['time'] != [] else 0,
                 100 * len(player['win']) / REPEAT / (len(playerResults) - 1),
                 len(player['win']),
                 '\n            '.join(player['win']),
                 len(player['lose']),
                 '\n            '.join(player['lose']),
                 len(player['violate']),
                 '\n            '.join(player['violate']),
                 len(player['timeout']),
                 '\n            '.join(player['timeout']),
                 len(player['error']),
                 '\n            '.join(player['error'])))
            player = playerResults[count][False]
            f.write('''defensive cases:
    average time: %.3f
        win rate: %.2f%%
        win: %d at
            %s
        lose: %d at
            %s
        violate: %d at
            %s
        timeout: %d at
            %s
        error: %d at
            %s
'''            %(sum(player['time']) / len(player['time']) if player['time'] != [] else 0,
                 100 * len(player['win']) / REPEAT / (len(playerResults) - 1),
                 len(player['win']),
                 '\n            '.join(player['win']),
                 len(player['lose']),
                 '\n            '.join(player['lose']),
                 len(player['violate']),
                 '\n            '.join(player['violate']),
                 len(player['timeout']),
                 '\n            '.join(player['timeout']),
                 len(player['error']),
                 '\n            '.join(player['error'])))
            f.write('=' * 50 + '\n')
            f.flush()
        f.close()

    # 打印报错信息
    if debug:
        f = open('%s/_Exceptions.txt' % match, 'w')
        for metamatch in matchResults['exception']:
            f.write('-> %s\n\n' % metamatch[0])
            f.write('offensive:\n')
            f.write(metamatch[1] if metamatch[1] else 'pass\n')
            f.write('\ndefensive:\n')
            f.write(metamatch[2] if metamatch[2] else 'pass\n')
            f.write('=' * 50 + '\n')
            f.flush()
        f.close()

    # 返回全部平台
    if toGet: return platforms

class mywindow(QMainWindow):
    def __init__(self):
        super(mywindow, self).__init__(None)
        self.load = False
    
    
    def loadmode(self, matchList = None, index = 1):
        # matchList = [mode, {'path': path, 'topText': topText, 'bottomText': bottomText}, ...]
        self.matchList = matchList
        self.index = index
        self.load = True
        self.ui.left.setEnabled(True)
        self.ui.right.setEnabled(True)
        self.ui.left.clicked.connect(self.previous)
        self.ui.right.clicked.connect(self.succ)
        self.ui.left.setText("后退\n(A)")
        self.ui.right.setText("前进\n(D)")
        if matchList == None:
            while True:  # 加载对局记录
                try:
                    x = QWidget()
                    self.log = open(QFileDialog.getOpenFileName(x,'选择文件','','Text files(*.txt)')[0], 'r').read().split('&')  # 读取全部记录并分成单条
                    self.size = len(self.log)
                    break
                except FileNotFoundError:
                    print('%s is not found.' % filename)

            print('=' * 50)
            '''while True:  # 选择模式
                self.mode = int(input('enter 0 for original mode.\nenter 1 for YuzuSoft mode.\nmode: '))
                if self.mode in range(2):
                    break
                else:
                    print('wrong input.')'''
            self.mode = 0
        else:
            self.match = self.matchList[index]
            self.log = open(self.match['path'], 'r').read().split('&')  # 读取全部记录并分成单条
            self.size = len(self.log)
            self.mode = self.matchList[0]
            
        self.statelabel.setText('press any key to start\nA previous step D next step')

        print('=' * 50)
        declarations = self.log[0].split('\n')
        for declaration in declarations:
            if declaration != '' and declaration[0] != '*':
                print(declaration)  # 打印说明信息

        '''if self.mode == 0:  # 2048原版
            for row in range(1, c.ROWS + 1):
                gridRow = []  # 一行方格
                for column in range(c.COLUMNS):
                    cell = Frame(background, bg=c.COLOR_NONE, width=c.LENGTH, height=c.LENGTH)  # 一个方格
                    cell.grid(row=row, column=column, padx=c.PADX, pady=c.PADY)
                    number = Label(cell, text='', bg=c.COLOR_NONE, justify=CENTER, font=c.FONT, width=c.WORD_SIZE[0],
                                   height=c.WORD_SIZE[1])
                    number.grid()
                    gridRow.append(number)
                self.gridCells.append(gridRow)

        if self.mode == 1:  # 柚子社版
            self.photos = {'+': [PhotoImage(file='../pic/%s_%d.png' % (c.PICTURES[0], _)) for _ in range(14)],
                           '-': [PhotoImage(file='../pic/%s_%d.png' % (c.PICTURES[1], _)) for _ in range(14)]}
            photo = PhotoImage(file='../pic/unknown.png')
            for row in range(1, c.ROWS + 1):
                gridRow = []  # 一行方格
                for column in range(c.COLUMNS):
                    cell = Frame(background)  # 一个方格
                    cell.grid(row=row, column=column, padx=c.PADX, pady=c.PADY)
                    number = Label(cell, image=photo)
                    number.grid()
                    gridRow.append(number)
                self.gridCells.append(gridRow)'''

        self.cur = 0        # 读取单条记录的游标
        self.state = True   # 游标运动的状态, True代表向前

    def analyse(self, log):
        # 分析指令
        if log[0] == 'e':    # 事件在顶端状态栏
            self.statelabel.setText(log.split(':')[1][:-1])
        elif log[0] == 'd':  # 决策在底端状态栏
            self.rounddisplay.setText(log.split(':')[0][1:])  # 当前轮数
            self.statelabel.setText(log.split(':')[1][:-1])
        elif log[0] == 'p':  # 更新棋盘
            self.rounddisplay.setText(log.split(':')[0][1:])  # 当前轮数
            
            platform = []
            pieces = log.split(':')[1].split()
            for piece in pieces:
                platform.append((piece[0], int(piece[1:])))
            cur = 0

            if self.mode == 0:  # 2048原版
                while cur < c.ROWS * c.COLUMNS:
                    row = cur // c.COLUMNS
                    column = cur % c.COLUMNS
                    belong, number = platform[cur]
                    if number == 0:
                        self.button[row][column].setStyleSheet("background-color:" + c.COLOR_CELL[belong])
                        self.button[row][column].setText("")
                    else:
                        self.button[row][column].setStyleSheet("background-color:" + c.COLOR_CELL[belong])
                        self.button[row][column].setText(str(2 ** number))
                    cur += 1

            '''if self.mode == 1:  # 柚子社版
                while cur < c.ROWS * c.COLUMNS:
                    row = cur // c.COLUMNS
                    column = cur % c.COLUMNS
                    belong, number = platform[cur]
                    self.gridCells[row][column].config(image=self.photos[belong][number])
                    cur += 1'''
    
    def previous(self):
        self.keyPressEvent(None, Qt.Key_A)
    
    def succ(self):
        self.keyPressEvent(None, Qt.Key_D)
    
    def keyPressEvent(self, event, key = None):
        print("1")
        if not self.load:
            return
        if key == None:
            key = event.key()
        if self.cur == 0:  # 第一条信息
            while True:
                self.cur += 1
                self.analyse(self.log[self.cur])
                if self.cur >= self.size - 1 or self.log[self.cur][0] != 'd':
                    break
        elif key == Qt.Key_A and self.cur > 1:     # 回退, 更新至决策
            while True:
                while self.log[self.cur - 1][0] == 'e':  # 忽略全部事件
                    self.cur -= 1
                if self.state:
                    if self.log[self.cur - 1][0] == 'd':  
                        self.cur -= 1
                    self.state = False
                self.cur -= 1
                self.analyse(self.log[self.cur])
                if self.cur <= 1 or self.log[self.cur][0] != 'p':
                    break
        elif key == Qt.Key_D and self.cur < self.size - 1:  # 前进, 更新至棋盘
            while True:
                if not self.state:
                    if self.log[self.cur + 1][0] == 'p':
                        self.cur += 1
                    self.state = True
                self.cur += 1
                self.analyse(self.log[self.cur])
                if self.cur >= self.size - 1 or self.log[self.cur][0] != 'd':
                    break
        elif key == Qt.Key_N and self.index != len(self.matchList) - 1:
            self.destroy()
            self.loadmode(self.matchList, self.index + 1)
        elif key == Qt.Key_P and self.index != 1:
            self.destroy()
            self.loadmode(self.matchList, self.index - 1)

class click():
    def __init__(self, x, y):
        self.pos = (x, y)
    def proc(self):
        global pos
        pos = self.pos
        print(pos)
        pass

class click1():
    def __init__(self, d):
        self.d = d
    def proc(self):
        global dirt
        dirt = self.d
        print(dirt)
        pass

class loadai_content(QItemDelegate):
    def __init__(self, parent = None):
        super(loadai_content, self).__init__(parent)

    def paint(self, painter, option, index):
        if not self.parent().indexWidget(index):
            if index.column() == 2:
                if index.row() < len(player_list):
                    button_read = QPushButton(
                        self.tr('删除ai'),
                        self.parent(),
                        clicked=self.parent().delai
                    )
                    button_read.index = [index.row(), index.column()]
                    h_box_layout = QHBoxLayout()
                    h_box_layout.addWidget(button_read)
                    h_box_layout.setContentsMargins(0, 0, 0, 0)
                    h_box_layout.setAlignment(Qt.AlignCenter)
                    widget = QWidget()
                    widget.setLayout(h_box_layout)
                    self.parent().setIndexWidget(
                        index,
                        widget
                    )
            elif index.column() == 1:
                if index.row() < len(player_list):
                    button_read = QCheckBox(
                        self.parent()
                    )
                    button_write = QPushButton(
                        self.tr('禁用') if player_state[index.row()] else self.tr('启用'),
                        self.parent(),
                        clicked=self.parent().cellButtonClicked
                    )
                    if player_state[index.row()]:
                        button_write.tr('禁用')
                    else:
                        button_write.tr('启用')
                    button_read.setChecked(player_state[index.row()])
                    button_read.stateChanged.connect(self.parent().cellButtonClicked)
                    button_read.index = [index.row(), index.column()]
                    button_write.index = [index.row(), index.column()]
                    h_box_layout = QHBoxLayout()
                    h_box_layout.addWidget(button_read)
                    h_box_layout.addWidget(button_write)
                    h_box_layout.setContentsMargins(0, 0, 0, 0)
                    h_box_layout.setAlignment(Qt.AlignCenter)
                    widget = QWidget()
                    widget.setLayout(h_box_layout)
                    self.parent().setIndexWidget(
                        index,
                        widget
                    )
            else:
                if index.row() < len(player_list):
                    button_read = QLabel(
                        self.tr(player_list[index.row()]),
                        self.parent()
                    )
                    button_read.index = [index.row(), index.column()]
                    h_box_layout = QHBoxLayout()
                    h_box_layout.addWidget(button_read)
                    h_box_layout.setContentsMargins(0, 0, 0, 0)
                    h_box_layout.setAlignment(Qt.AlignCenter)
                    widget = QWidget()
                    widget.setLayout(h_box_layout)
                    self.parent().setIndexWidget(
                        index,
                        widget
                    )
                else:
                    button_read = QPushButton(
                        self.tr('添加ai'),
                        self.parent(),
                        clicked=self.parent().openfile
                    )
                    button_read.index = [index.row(), index.column()]
                    h_box_layout = QHBoxLayout()
                    h_box_layout.addWidget(button_read)
                    h_box_layout.setContentsMargins(0, 0, 0, 0)
                    h_box_layout.setAlignment(Qt.AlignCenter)
                    widget = QWidget()
                    widget.setLayout(h_box_layout)
                    self.parent().setIndexWidget(
                        index,
                        widget
                    )


class MyModel(QAbstractTableModel):
    global playerlist
    def __init__(self, parent=None):
        super(MyModel, self).__init__(parent)

    def rowCount(self, QModelIndex):
        return len(player_list) + 1

    def columnCount(self, QModelIndex):
        return 3

    def data(self, index, role):
        row = index.row()
        col = index.column()
        return QVariant()
    
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return QVariant()
        elif orientation == Qt.Horizontal:
            return ['路径','状态','操作'][section]
        else:
            return "%d" % (section + 1)


class ai_load(QTableView):
    global ui, load
    def __init__(self, parent = None):
        super(ai_load, self).__init__(parent)
        self.setItemDelegate(loadai_content(self))

    def cellButtonClicked(self):
        player_state[self.sender().index[0]] = not player_state[self.sender().index[0]]
        loadai()

    def delai(self):
        player_list.pop(self.sender().index[0])
        player_state.pop(self.sender().index[0])
        loadai()
    
    def openfile(self):
        global cnt
        x = QWidget()
        c=QFileDialog.getOpenFileName(x,'选择文件','','Python files(*.py)')[0]
        player_list.append(c)
        player_state.append(True)
        loadai()


def settings():
    global dialog1
    ui_settings = dialog.Ui_settings()
    dialog1 = QDialog()
    ui_settings.setupUi(dialog1)
    def savechanged():
        toSave = ui_settings.checkBox.isChecked()
    def reportchanged():
        toReport = ui_settings.checkBox_2.isChecked()
    def debugchanged():
        debug = ui_settings.checkBox_3.isChecked()
    def timechanged():
        MAXTIME = ui_settings.textEdit.toPlainText()
    def roundchanged():
        ROUNDS = ui_settings.textEdit_2.toPlainText()
    ui_settings.checkBox.setChecked(toSave)
    ui_settings.checkBox.stateChanged.connect(savechanged)
    ui_settings.checkBox_2.setChecked(toReport)
    ui_settings.checkBox_2.stateChanged.connect(reportchanged)
    ui_settings.checkBox_3.setChecked(debug)
    ui_settings.checkBox_3.stateChanged.connect(debugchanged)
    ui_settings.textEdit.setText(str(MAXTIME))
    ui_settings.pushButton.clicked.connect(timechanged)
    ui_settings.textEdit_2.setText(str(ROUNDS))
    ui_settings.pushButton_2.clicked.connect(roundchanged)
    dialog1.show()

class setmode():
    def __init__(self, set_mode):
        self.mode = set_mode
    def proc(self):
        global mode
        mode = self.mode
        if mode == 1:
            statelabel.setText("当前模式为电脑-电脑")
        elif mode == 2:
            statelabel.setText("当前模式为电脑-人类")
        elif mode == 3:
            statelabel.setText("当前模式为人类-电脑")
        else:
            statelabel.setText("当前模式为人类-人类")

def work():
    if phase == 0:
        if pos != None and plat_cur != None:
            if plat_cur.get_position(plat_cur.pf, plat_cur.rnd):
                next(matct_object)
            else:
                x = QWidget()
                QMessageBox.information(x, "提示", "位置非法", QMessageBox.Yes)
    else:
        if dirt != None and plat_cur != None:
            if plat_cur.get_direction(plat_cur.pf, plat_cur.rnd):
                next(matct_object)
            else:
                x = QWidget()
                QMessageBox.information(x, "提示", "方向非法", QMessageBox.Yes)

def match_init():
    plst = []
    for _ in range(len(player_list)):
        if player_state[_]:
            plst.append(player_list[_])
    if mode == 0:
        global ui
        x = QWidget()
        QMessageBox.information(x, "提示", "尚未选择模式", QMessageBox.Yes)
        return
    elif mode == 1:
        if len(plst) < 2:
            x = QWidget()
            QMessageBox.information(x, "提示", "ai数量小于两个", QMessageBox.Yes)
        else:
            main(plst, toSave = toSave, toReport = toReport, debug = False, MAXTIME = MAXTIME, ROUNDS = ROUNDS)
    elif mode == 2:
        if len(plst) != 1:
            x = QWidget()
            QMessageBox.information(x, "提示", "请只启用一个ai", QMessageBox.Yes)
        else:
            main(plst + ["human"], toSave = toSave, toReport = False, debug = False, MAXTIME = MAXTIME, ROUNDS = ROUNDS)
    elif mode == 3:
        if len(plst) != 1:
            x = QWidget()
            QMessageBox.information(x, "提示", "请只启用一个ai", QMessageBox.Yes)
        else:
            main(plst + ["human"], toSave = toSave, toReport = False, debug = False, MAXTIME = MAXTIME, ROUNDS = ROUNDS)
    else:
        main(plst, toSave = toSave, toReport = toReport, debug = False, MAXTIME = MAXTIME, ROUNDS = ROUNDS)
    x = QWidget()
    QMessageBox.information(x, "提示", "已完成", QMessageBox.Yes)
    

player_list = []
player_state = []
mode = 0
cnt = 0
toSave, toReport, debug, MAXTIME, ROUNDS = True, True, False, c.MAXTIME, c.ROUNDS

if __name__ == '__main__':
    global ui
    app = QApplication(sys.argv)
    MainWindow = mywindow()
    ui = gui.Ui_MainWindow()
    ui.setupUi(MainWindow)
    button = [[QtWidgets.QPushButton() for _ in range(0, c.COLUMNS)] for _ in range(0, c.ROWS)]
    table = [[None for _ in range(0, c.COLUMNS)] for _ in range(0, c.ROWS)]
    for i in range(c.ROWS):
        for j in range(c.COLUMNS):
            ui.chessboard.addWidget(button[i][j], i, j)
            button[i][j].setFixedSize(QtCore.QSize(60, 60))
            table[i][j] = click(i, j)
            #button[i][j].clicked.connect(table[i][j].proc)
            #button[i][j].setEnabled(False)
    MainWindow.button = button
    MainWindow.rounddisplay = ui.rounddisplay
    MainWindow.statelabel = ui.statelabel
    MainWindow.ui = ui
    def loadai():
        global load
        load = ai_load()
        myModel = MyModel()
        load.setModel(myModel)
        load.resize(1000,600)
        load.setColumnWidth(0, 600)
        load.show()
    ui.ai_set.triggered.connect(loadai)
    ui.match_settings.triggered.connect(settings)
    dirtlst = [click1(_) for _ in range(4)]
    ui.up.clicked.connect(dirtlst[0].proc)
    ui.down.clicked.connect(dirtlst[1].proc)
    ui.left.clicked.connect(dirtlst[2].proc)
    ui.right.clicked.connect(dirtlst[3].proc)
    ui.confirm.clicked.connect(work)
    modelst = [setmode(_) for _ in range(1,5)]
    ui.mode1.triggered.connect(modelst[0].proc)
    ui.mode2.triggered.connect(modelst[1].proc)
    ui.mode3.triggered.connect(modelst[2].proc)
    ui.mode4.triggered.connect(modelst[3].proc)
    ui.start.triggered.connect(match_init)
    def loadmode():
        MainWindow.loadmode()
    ui.loadfile.triggered.connect(loadmode)
    def about():
        x = QWidget()
        QMessageBox.information(x, "说明", "本程序对之前的调试工具做了整合，并制作了可视化界面\n什么，你问我为什么那么多按钮不能用？\n因为功能没做出来（悲，后面会尽力补全", QMessageBox.Yes)
    ui.about.triggered.connect(about)
    statelabel = ui.statelabel
    MainWindow.show()
    sys.exit(app.exec_())