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
        this.gameSpeed = 150;
        this.soundEnabled = true;
        this.difficulty = 'medium';
        
        this.initializeElements();
        this.setupEventListeners();
        this.generateFood();
        this.updateDisplay();
        this.showOverlay();
    }
    
    initializeElements() {
        this.scoreElement = document.getElementById('score');
        this.highScoreElement = document.getElementById('high-score');
        this.speedElement = document.getElementById('speed');
        this.overlay = document.getElementById('gameOverlay');
        this.startButton = document.getElementById('startButton');
        this.pauseButton = document.getElementById('pauseBtn');
        this.restartButton = document.getElementById('restartBtn');
        this.difficultySelect = document.getElementById('difficulty');
        this.soundToggle = document.getElementById('sound');
        
        // 移动端控制按钮
        this.mobileUp = document.getElementById('mobileUp');
        this.mobileDown = document.getElementById('mobileDown');
        this.mobileLeft = document.getElementById('mobileLeft');
        this.mobileRight = document.getElementById('mobileRight');
        
        // 桌面端控制按钮
        this.upBtn = document.getElementById('upBtn');
        this.downBtn = document.getElementById('downBtn');
        this.leftBtn = document.getElementById('leftBtn');
        this.rightBtn = document.getElementById('rightBtn');
    }
    
    setupEventListeners() {
        // 键盘控制
        document.addEventListener('keydown', (e) => this.handleKeyPress(e));
        
        // 按钮控制
        this.startButton.addEventListener('click', () => this.startGame());
        this.pauseButton.addEventListener('click', () => this.togglePause());
        this.restartButton.addEventListener('click', () => this.restartGame());
        this.difficultySelect.addEventListener('change', (e) => this.changeDifficulty(e.target.value));
        this.soundToggle.addEventListener('change', (e) => this.toggleSound(e.target.checked));
        
        // 移动端控制
        this.mobileUp.addEventListener('click', () => this.changeDirection(0, -1));
        this.mobileDown.addEventListener('click', () => this.changeDirection(0, 1));
        this.mobileLeft.addEventListener('click', () => this.changeDirection(-1, 0));
        this.mobileRight.addEventListener('click', () => this.changeDirection(1, 0));
        
        // 桌面端按钮控制
        this.upBtn.addEventListener('click', () => this.changeDirection(0, -1));
        this.downBtn.addEventListener('click', () => this.changeDirection(0, 1));
        this.leftBtn.addEventListener('click', () => this.changeDirection(-1, 0));
        this.rightBtn.addEventListener('click', () => this.changeDirection(1, 0));
        
        // 防止页面滚动
        document.addEventListener('keydown', (e) => {
            if(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
                e.preventDefault();
            }
        });
    }
    
    handleKeyPress(e) {
        if (!this.gameRunning || this.gamePaused) return;
        
        switch(e.key) {
            case 'ArrowUp':
            case 'w':
            case 'W':
                this.changeDirection(0, -1);
                break;
            case 'ArrowDown':
            case 's':
            case 'S':
                this.changeDirection(0, 1);
                break;
            case 'ArrowLeft':
            case 'a':
            case 'A':
                this.changeDirection(-1, 0);
                break;
            case 'ArrowRight':
            case 'd':
            case 'D':
                this.changeDirection(1, 0);
                break;
            case ' ':
                this.togglePause();
                break;
            case 'r':
            case 'R':
                this.restartGame();
                break;
        }
    }
    
    changeDirection(newDx, newDy) {
        if (!this.gameRunning || this.gamePaused) return;
        
        // 防止蛇直接掉头
        if (this.dx === -newDx && this.dy === -newDy) return;
        
        this.dx = newDx;
        this.dy = newDy;
    }
    
    startGame() {
        this.gameRunning = true;
        this.gamePaused = false;
        this.hideOverlay();
        this.gameLoop();
    }
    
    togglePause() {
        if (!this.gameRunning) return;
        
        this.gamePaused = !this.gamePaused;
        this.pauseButton.textContent = this.gamePaused ? '继续' : '暂停';
        
        if (!this.gamePaused) {
            this.gameLoop();
        }
    }
    
    restartGame() {
        this.snake = [{x: 10, y: 10}];
        this.dx = 0;
        this.dy = 0;
        this.score = 0;
        this.gameRunning = false;
        this.gamePaused = false;
        this.pauseButton.textContent = '暂停';
        this.generateFood();
        this.updateDisplay();
        this.showOverlay();
        this.draw();
    }
    
    changeDifficulty(level) {
        this.difficulty = level;
        switch(level) {
            case 'easy':
                this.gameSpeed = 200;
                break;
            case 'medium':
                this.gameSpeed = 150;
                break;
            case 'hard':
                this.gameSpeed = 100;
                break;
        }
        this.speedElement.textContent = level === 'easy' ? '1' : level === 'medium' ? '2' : '3';
    }
    
    toggleSound(enabled) {
        this.soundEnabled = enabled;
    }
    
    generateFood() {
        this.food = {
            x: Math.floor(Math.random() * this.tileCount),
            y: Math.floor(Math.random() * this.tileCount)
        };
        
        // 确保食物不在蛇身上
        for (let segment of this.snake) {
            if (segment.x === this.food.x && segment.y === this.food.y) {
                this.generateFood();
                return;
            }
        }
    }
    
    update() {
        if (!this.gameRunning || this.gamePaused) return;
        
        const head = {x: this.snake[0].x + this.dx, y: this.snake[0].y + this.dy};
        
        // 检查碰撞
        if (this.checkCollision(head)) {
            this.gameOver();
            return;
        }
        
        this.snake.unshift(head);
        
        // 检查是否吃到食物
        if (head.x === this.food.x && head.y === this.food.y) {
            this.score += 10;
            this.generateFood();
            this.playSound('eat');
            this.addPulseEffect();
        } else {
            this.snake.pop();
        }
        
        this.updateDisplay();
    }
    
    checkCollision(head) {
        // 检查墙壁碰撞
        if (head.x < 0 || head.x >= this.tileCount || head.y < 0 || head.y >= this.tileCount) {
            return true;
        }
        
        // 检查自身碰撞
        for (let segment of this.snake) {
            if (head.x === segment.x && head.y === segment.y) {
                return true;
            }
        }
        
        return false;
    }
    
    draw() {
        // 清空画布
        this.ctx.fillStyle = '#2c3e50';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制网格
        this.drawGrid();
        
        // 绘制蛇
        this.drawSnake();
        
        // 绘制食物
        this.drawFood();
    }
    
    drawGrid() {
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
        this.ctx.lineWidth = 1;
        
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
    }
    
    drawSnake() {
        this.snake.forEach((segment, index) => {
            const gradient = this.ctx.createLinearGradient(
                segment.x * this.gridSize, 
                segment.y * this.gridSize,
                (segment.x + 1) * this.gridSize, 
                (segment.y + 1) * this.gridSize
            );
            
            if (index === 0) {
                // 蛇头
                gradient.addColorStop(0, '#ff6b6b');
                gradient.addColorStop(1, '#ff5252');
            } else {
                // 蛇身
                gradient.addColorStop(0, '#4ecdc4');
                gradient.addColorStop(1, '#26a69a');
            }
            
            this.ctx.fillStyle = gradient;
            this.ctx.fillRect(
                segment.x * this.gridSize + 2,
                segment.y * this.gridSize + 2,
                this.gridSize - 4,
                this.gridSize - 4
            );
            
            // 添加光泽效果
            this.ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
            this.ctx.fillRect(
                segment.x * this.gridSize + 4,
                segment.y * this.gridSize + 4,
                this.gridSize - 12,
                4
            );
        });
    }
    
    drawFood() {
        const centerX = this.food.x * this.gridSize + this.gridSize / 2;
        const centerY = this.food.y * this.gridSize + this.gridSize / 2;
        const radius = this.gridSize / 2 - 4;
        
        // 绘制食物（圆形）
        const gradient = this.ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);
        gradient.addColorStop(0, '#feca57');
        gradient.addColorStop(1, '#ff9ff3');
        
        this.ctx.fillStyle = gradient;
        this.ctx.beginPath();
        this.ctx.arc(centerX, centerY, radius, 0, 2 * Math.PI);
        this.ctx.fill();
        
        // 添加光泽效果
        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
        this.ctx.beginPath();
        this.ctx.arc(centerX - 3, centerY - 3, radius / 3, 0, 2 * Math.PI);
        this.ctx.fill();
    }
    
    updateDisplay() {
        this.scoreElement.textContent = this.score;
        this.highScoreElement.textContent = this.highScore;
        
        // 更新最高分
        if (this.score > this.highScore) {
            this.highScore = this.score;
            localStorage.setItem('snakeHighScore', this.highScore);
        }
    }
    
    showOverlay() {
        this.overlay.style.display = 'flex';
    }
    
    hideOverlay() {
        this.overlay.style.display = 'none';
    }
    
    gameOver() {
        this.gameRunning = false;
        this.playSound('gameOver');
        this.overlay.classList.add('game-over');
        this.overlay.innerHTML = `
            <div class="overlay-content">
                <h2>游戏结束!</h2>
                <p>最终得分: ${this.score}</p>
                <p>${this.score === this.highScore ? '🎉 新纪录！' : ''}</p>
                <button class="start-button" id="restartButton">重新开始</button>
            </div>
        `;
        
        document.getElementById('restartButton').addEventListener('click', () => {
            this.overlay.classList.remove('game-over');
            this.restartGame();
        });
        
        this.showOverlay();
    }
    
    playSound(type) {
        if (!this.soundEnabled) return;
        
        // 创建音频上下文
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        
        switch(type) {
            case 'eat':
                oscillator.frequency.setValueAtTime(800, audioContext.currentTime);
                oscillator.frequency.exponentialRampToValueAtTime(1200, audioContext.currentTime + 0.1);
                gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.1);
                break;
            case 'gameOver':
                oscillator.frequency.setValueAtTime(400, audioContext.currentTime);
                oscillator.frequency.exponentialRampToValueAtTime(200, audioContext.currentTime + 0.3);
                gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
                break;
        }
        
        oscillator.start();
        oscillator.stop(audioContext.currentTime + 0.3);
    }
    
    addPulseEffect() {
        this.canvas.classList.add('pulse');
        setTimeout(() => {
            this.canvas.classList.remove('pulse');
        }, 300);
    }
    
    gameLoop() {
        if (!this.gameRunning || this.gamePaused) return;
        
        this.update();
        this.draw();
        
        setTimeout(() => {
            this.gameLoop();
        }, this.gameSpeed);
    }
}

// 初始化游戏
document.addEventListener('DOMContentLoaded', () => {
    const game = new SnakeGame();
    
    // 添加淡入效果
    document.querySelector('.game-container').classList.add('fade-in');
});

// 防止移动端双击缩放
let lastTouchEnd = 0;
document.addEventListener('touchend', (e) => {
    const now = Date.now();
    if (now - lastTouchEnd <= 300) {
        e.preventDefault();
    }
    lastTouchEnd = now;
}, false);

// 检测移动设备
function isMobile() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
}

// 根据设备类型显示/隐藏移动控制
if (isMobile()) {
    document.getElementById('mobileControls').style.display = 'flex';
    document.querySelector('.control-buttons').style.display = 'none';
} else {
    document.getElementById('mobileControls').style.display = 'none';
    document.querySelector('.control-buttons').style.display = 'grid';
}