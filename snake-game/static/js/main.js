class SnakeGame {
    constructor() {
        this.canvas = document.getElementById('gameCanvas');
        this.ctx = this.canvas.getContext('2d');
        this.gridSize = 20;
        this.tileCount = this.canvas.width / this.gridSize;
        
        this.snake = [
            {x: 10, y: 10}
        ];
        this.food = {};
        this.dx = 0;
        this.dy = 0;
        this.score = 0;
        this.highScore = localStorage.getItem('snakeHighScore') || 0;
        this.gameRunning = false;
        this.gamePaused = false;
        
        this.initializeGame();
        this.setupEventListeners();
        this.updateHighScore();
    }
    
    initializeGame() {
        this.generateFood();
        this.drawGame();
    }
    
    setupEventListeners() {
        // 键盘事件
        document.addEventListener('keydown', (e) => {
            if (!this.gameRunning) return;
            
            switch(e.key) {
                case 'ArrowUp':
                    if (this.dy !== 1) {
                        this.dx = 0;
                        this.dy = -1;
                    }
                    break;
                case 'ArrowDown':
                    if (this.dy !== -1) {
                        this.dx = 0;
                        this.dy = 1;
                    }
                    break;
                case 'ArrowLeft':
                    if (this.dx !== 1) {
                        this.dx = -1;
                        this.dy = 0;
                    }
                    break;
                case 'ArrowRight':
                    if (this.dx !== -1) {
                        this.dx = 1;
                        this.dy = 0;
                    }
                    break;
                case ' ':
                    this.togglePause();
                    break;
            }
        });
        
        // 按钮事件
        document.getElementById('startBtn').addEventListener('click', () => {
            this.startGame();
        });
        
        document.getElementById('pauseBtn').addEventListener('click', () => {
            this.togglePause();
        });
        
        document.getElementById('restartBtn').addEventListener('click', () => {
            this.restartGame();
        });
        
        // 控制按钮事件
        document.getElementById('upBtn').addEventListener('click', () => {
            if (this.gameRunning && this.dy !== 1) {
                this.dx = 0;
                this.dy = -1;
            }
        });
        
        document.getElementById('downBtn').addEventListener('click', () => {
            if (this.gameRunning && this.dy !== -1) {
                this.dx = 0;
                this.dy = 1;
            }
        });
        
        document.getElementById('leftBtn').addEventListener('click', () => {
            if (this.gameRunning && this.dx !== 1) {
                this.dx = -1;
                this.dy = 0;
            }
        });
        
        document.getElementById('rightBtn').addEventListener('click', () => {
            if (this.gameRunning && this.dx !== -1) {
                this.dx = 1;
                this.dy = 0;
            }
        });
    }
    
    startGame() {
        this.gameRunning = true;
        this.gamePaused = false;
        this.dx = 1;
        this.dy = 0;
        document.getElementById('gameOverlay').style.display = 'none';
        this.gameLoop();
    }
    
    togglePause() {
        if (!this.gameRunning) return;
        
        this.gamePaused = !this.gamePaused;
        const pauseBtn = document.getElementById('pauseBtn');
        
        if (this.gamePaused) {
            pauseBtn.textContent = '继续';
            pauseBtn.style.background = 'linear-gradient(145deg, #48bb78, #38a169)';
        } else {
            pauseBtn.textContent = '暂停';
            pauseBtn.style.background = 'linear-gradient(145deg, #9f7aea, #805ad5)';
            this.gameLoop();
        }
    }
    
    restartGame() {
        this.gameRunning = false;
        this.gamePaused = false;
        this.snake = [{x: 10, y: 10}];
        this.dx = 0;
        this.dy = 0;
        this.score = 0;
        this.updateScore();
        this.generateFood();
        this.drawGame();
        
        document.getElementById('gameOverlay').style.display = 'flex';
        document.getElementById('pauseBtn').textContent = '暂停';
        document.getElementById('pauseBtn').style.background = 'linear-gradient(145deg, #9f7aea, #805ad5)';
    }
    
    generateFood() {
        this.food = {
            x: Math.floor(Math.random() * this.tileCount),
            y: Math.floor(Math.random() * this.tileCount)
        };
        
        // 确保食物不会生成在蛇身上
        for (let segment of this.snake) {
            if (segment.x === this.food.x && segment.y === this.food.y) {
                this.generateFood();
                return;
            }
        }
    }
    
    drawGame() {
        // 清空画布
        this.ctx.fillStyle = '#2d3748';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制网格线
        this.ctx.strokeStyle = '#4a5568';
        this.ctx.lineWidth = 0.5;
        for (let i = 0; i <= this.tileCount; i++) {
            this.ctx.beginPath();
            this.ctx.moveTo(i * this.gridSize, 0);
            this.ctx.lineTo(i * this.gridSize, this.canvas.height);
            this.ctx.stroke();
            
            this.ctx.beginPath();
            this.ctx.moveTo(0, i * this.gridSize);
            this.ctx.lineTo(this.canvas.width, i * this.gridSize);
            this.ctx.stroke();
        }
        
        // 绘制蛇
        this.snake.forEach((segment, index) => {
            if (index === 0) {
                // 蛇头
                this.ctx.fillStyle = '#68d391';
                this.ctx.shadowColor = '#48bb78';
                this.ctx.shadowBlur = 10;
            } else {
                // 蛇身
                this.ctx.fillStyle = '#48bb78';
                this.ctx.shadowBlur = 5;
            }
            
            this.ctx.fillRect(
                segment.x * this.gridSize + 1,
                segment.y * this.gridSize + 1,
                this.gridSize - 2,
                this.gridSize - 2
            );
        });
        
        // 重置阴影
        this.ctx.shadowBlur = 0;
        
        // 绘制食物
        this.ctx.fillStyle = '#f56565';
        this.ctx.shadowColor = '#e53e3e';
        this.ctx.shadowBlur = 15;
        this.ctx.beginPath();
        this.ctx.arc(
            this.food.x * this.gridSize + this.gridSize / 2,
            this.food.y * this.gridSize + this.gridSize / 2,
            this.gridSize / 2 - 2,
            0,
            2 * Math.PI
        );
        this.ctx.fill();
        
        // 重置阴影
        this.ctx.shadowBlur = 0;
    }
    
    updateGame() {
        if (!this.gameRunning || this.gamePaused) return;
        
        // 移动蛇头
        const head = {x: this.snake[0].x + this.dx, y: this.snake[0].y + this.dy};
        
        // 检查墙壁碰撞
        if (head.x < 0 || head.x >= this.tileCount || head.y < 0 || head.y >= this.tileCount) {
            this.gameOver();
            return;
        }
        
        // 检查自身碰撞
        for (let segment of this.snake) {
            if (head.x === segment.x && head.y === segment.y) {
                this.gameOver();
                return;
            }
        }
        
        this.snake.unshift(head);
        
        // 检查是否吃到食物
        if (head.x === this.food.x && head.y === this.food.y) {
            this.score += 10;
            this.updateScore();
            this.generateFood();
            
            // 添加得分动画效果
            const scoreElement = document.getElementById('score');
            scoreElement.classList.add('pulse');
            setTimeout(() => {
                scoreElement.classList.remove('pulse');
            }, 500);
        } else {
            this.snake.pop();
        }
        
        this.drawGame();
    }
    
    gameOver() {
        this.gameRunning = false;
        
        // 更新最高分
        if (this.score > this.highScore) {
            this.highScore = this.score;
            localStorage.setItem('snakeHighScore', this.highScore);
            this.updateHighScore();
        }
        
        // 显示游戏结束界面
        const overlay = document.getElementById('gameOverlay');
        const overlayContent = overlay.querySelector('.overlay-content');
        
        overlayContent.innerHTML = `
            <h2>游戏结束！</h2>
            <p>你的得分: ${this.score}</p>
            ${this.score === this.highScore ? '<p>🎉 新纪录！</p>' : ''}
            <button id="restartBtn2" class="btn">重新开始</button>
        `;
        
        overlay.style.display = 'flex';
        
        // 绑定重新开始按钮
        document.getElementById('restartBtn2').addEventListener('click', () => {
            this.restartGame();
        });
    }
    
    updateScore() {
        document.getElementById('score').textContent = this.score;
    }
    
    updateHighScore() {
        document.getElementById('highScore').textContent = this.highScore;
    }
    
    gameLoop() {
        if (!this.gameRunning || this.gamePaused) return;
        
        this.updateGame();
        setTimeout(() => {
            this.gameLoop();
        }, 150);
    }
}

// 初始化游戏
document.addEventListener('DOMContentLoaded', () => {
    const game = new SnakeGame();
});